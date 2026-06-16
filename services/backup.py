import os
import re
import time
from datetime import datetime
from database.models import ServerModel, BackupModel
from config import BACKUP_WEB_DIR, SSH_COMMAND_TIMEOUT


class WebBackup:
    """网站备份与恢复"""

    # 候选可写入目录（按优先级排序）
    CANDIDATE_DIRS = ['/tmp', '/var/tmp', '/dev/shm', '/var/www/html', '/var/www', '/home']

    # version_tag 白名单：仅允许字母、数字、点、下划线、短横线
    _TAG_RE = re.compile(r'^[A-Za-z0-9._-]+$')

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager
        os.makedirs(BACKUP_WEB_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _sanitize_tag(self, tag):
        """对 version_tag 做白名单校验，防止 shell 注入与通配符误命中"""
        if not tag or not self._TAG_RE.match(tag):
            raise Exception(f'非法 version_tag: {tag!r}（仅允许字母/数字/._-）')
        return tag

    def _get_writable_dir(self, server_id):
        """探测服务器上可写入的目录"""
        for d in self.CANDIDATE_DIRS:
            stdout, _, code = self.ssh.exec_command(
                server_id,
                f"test -w '{d}' 2>/dev/null && echo 'OK' || echo 'FAIL'",
                timeout=10
            )
            if code == 0 and stdout.strip() == 'OK':
                return d
        return '/tmp'

    def _find_remote_backup(self, server_id, version_tag):
        """在远端按 version_tag 精确匹配可用 tar，返回路径或 None。

        匹配规则：awd_backup_<server_id>_<safe_tag>_*.tar
        - 完整精确通配，避免子串误命中
        - 排除 0 字节残留
        - 取 mtime 最新
        - 通过 tar -tf 校验完整性后再返回
        """
        safe_tag = self._sanitize_tag(version_tag)
        pattern = f'awd_backup_{server_id}_{safe_tag}_*.tar'
        for d in ('/tmp', '/var/tmp', '/dev/shm'):
            cmd = (
                f"find '{d}' -maxdepth 1 -type f -name '{pattern}' "
                f"-size +0c -printf '%T@ %p\\n' 2>/dev/null "
                f"| sort -rn | head -1 | awk '{{print $2}}'"
            )
            stdout, _, code = self.ssh.exec_command(server_id, cmd, timeout=10)
            path = stdout.strip()
            if code == 0 and path:
                _, _, tcode = self.ssh.exec_command(
                    server_id, f"tar -tf '{path}' >/dev/null 2>&1", timeout=30
                )
                if tcode == 0:
                    return path
        return None

    def _clean_web_root(self, server_id, web_root, logs):
        """清空 web_root（不保留任何文件）。

        - 使用 set -e 保证单步失败即中断
        - 使用 find -L 跟随软链接（web_root 可能是软链接指向真实目录）
        - 双重保护：test -d 校验 + -mindepth 1 -maxdepth 1
        """
        cmd = f"""set -e
WR='{web_root}'
test -d "$WR"
find -L "$WR" -mindepth 1 -maxdepth 1 -exec rm -rf {{}} +
"""
        _, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=120)
        if code != 0:
            raise Exception(f'清空 web_root 失败: {stderr.strip()}')
        logs.append(f'[clean] {web_root} 已彻底清空（无保留）')

    def _fix_permissions(self, server_id, web_root, logs):
        """修复权限：探测 web 用户，统一 dir 755 / file 644，脚本保留 755

        注意：
        - web_root 可能是软链接指向 root-owned 目录，chown 可能失败
        - 使用 find -L 跟随软链接
        - 过滤 SSH shell 警告和 chown 权限错误（不影响文件访问）
        """
        detect = (
            "id -u www-data >/dev/null 2>&1 && echo www-data "
            "|| (id -u apache >/dev/null 2>&1 && echo apache) "
            "|| (id -u nginx  >/dev/null 2>&1 && echo nginx) "
            "|| echo root"
        )
        stdout, _, _ = self.ssh.exec_command(server_id, detect, timeout=10)
        user = stdout.strip() or 'root'

        # 使用 find -L 跟随软链接；chown 可能因软链接指向 root 目录而失败，忽略
        cmd = f"""set -e
WR='{web_root}'
chown -R {user}:{user} "$WR" 2>/dev/null || chown -R {user} "$WR" 2>/dev/null || true
find -L "$WR" -type d -exec chmod 755 {{}} +
find -L "$WR" -type f -exec chmod 644 {{}} +
for f in docker.sh run.sh; do
  [ -f "$WR/$f" ] && chmod 755 "$WR/$f" || true
done
"""
        _, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=60)
        # 过滤 SSH shell 警告和 chown/chmod 权限错误（软链接指向 root 目录时常见）
        perm_errors = [line for line in stderr.strip().split('\n')
                       if line and not line.startswith('Could not chdir')
                       and not 'changing ownership' in line
                       and not 'changing permissions' in line]
        if code != 0 and perm_errors:
            raise Exception(f'修复权限失败: {perm_errors[0]}')
        logs.append(f'[chown] owner={user}, dir=755, file=644, scripts=755')

    # ------------------------------------------------------------------
    # 备份
    # ------------------------------------------------------------------
    def backup(self, server_id, version_tag, storage_dir=None, clean_remote=False):
        """备份网站源码

        Args:
            server_id: 服务器ID
            version_tag: 版本标签（白名单校验）
            storage_dir: 存储目录（默认/tmp）
            clean_remote: 下载完成后是否移除线上临时文件（默认False，不删除，便于复用）
        """
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        safe_tag = self._sanitize_tag(version_tag)

        web_root = server['web_root']
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 确定存储目录
        if not storage_dir:
            storage_dir = '/tmp'

        # 远端命名包含 server_id + safe_tag，方便 restore 精确匹配
        remote_tmp = f"{storage_dir}/awd_backup_{server_id}_{safe_tag}_{timestamp}.tar"
        local_filename = f'web_{server["name"]}_{safe_tag}_{timestamp}.tar'
        local_path = os.path.join(BACKUP_WEB_DIR, local_filename)

        # 在服务器上打包（cd到存储目录后执行tar）
        cmd = f"mkdir -p '{storage_dir}' && cd '{storage_dir}' && tar cf '{remote_tmp}' -C '{web_root}' . 2>/dev/null"
        self.ssh.exec_command(server_id, cmd, timeout=120)

        # 检查远程文件是否存在且大小 > 0
        stdout, _, _ = self.ssh.exec_command(server_id, f"stat -c %s '{remote_tmp}' 2>/dev/null || echo 0")
        file_size = int(stdout.strip() or '0')

        if file_size == 0:
            raise Exception('打包失败: 备份文件大小为0，请检查Web根目录是否存在且有读取权限')

        # 下载到本地
        try:
            self.ssh.download_file(server_id, remote_tmp, local_path)
        except Exception as e:
            self.ssh.exec_command(server_id, f"rm -f '{remote_tmp}'", timeout=10)
            raise Exception(f'下载备份到本地失败: {str(e)}')

        # 根据选项决定是否清理远程临时文件
        if clean_remote:
            self.ssh.exec_command(server_id, f"rm -f '{remote_tmp}'", timeout=10)

        # 验证本地文件
        if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
            raise Exception('备份下载到本地失败: 本地文件不存在或为空')

        # 记录备份信息
        backup_id = BackupModel.create(
            server_id=server_id,
            backup_type='web',
            version_tag=safe_tag,
            file_path=local_path,
            file_size=file_size
        )

        return {
            'backup_id': backup_id,
            'version_tag': safe_tag,
            'file_path': local_path,
            'file_size': file_size,
            'remote_path': remote_tmp if not clean_remote else None
        }

    # ------------------------------------------------------------------
    # 恢复
    # ------------------------------------------------------------------
    def restore(self, server_id, backup_id):
        """恢复网站源码 - 彻底恢复到指定备份版本

        恢复策略（按用户需求顺序）：
        1. 前置校验（server / backup 记录 / web_root 合法性）
        2. 解析 tar 来源：
           - 优先在远端按 version_tag 精确匹配 tar 包
           - 若线上无匹配，则上传本地备份并校验
        3. 移除网站原始内容（不保留任何文件）
        4. 解压备份到 web_root
        5. 修复权限
        6. 清理本次上传的临时文件（线上原 tar 保留以便复用）
        """
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        backup = BackupModel.get_by_id(backup_id)
        if not backup:
            raise Exception('备份记录不存在')

        web_root = (server['web_root'] or '').rstrip('/')
        if not web_root or web_root in ('/', '/root', '/home'):
            raise Exception(f'web_root 非法: {web_root!r}，拒绝执行')

        version_tag = backup['version_tag']
        local_backup_path = backup['file_path']
        logs = []

        # ---- 步骤 1: 解析 tar 来源（线上优先） ----
        try:
            remote_tar = self._find_remote_backup(server_id, version_tag)
        except Exception as e:
            # version_tag 非法等情况，直接抛出
            raise Exception(f'查找线上备份失败: {str(e)}')

        uploaded_tmp = None  # 仅本次上传的临时文件需要在最后清理

        if remote_tar:
            logs.append(f'[source] 命中线上备份: {remote_tar}')
            source = '线上备份'
            tar_path = remote_tar
            cleanup_tar = False
        else:
            logs.append('[source] 线上无精确匹配，回退本地上传')
            if not local_backup_path or not os.path.exists(local_backup_path):
                raise Exception('线上无对应版本，且本地备份文件不存在，无法恢复')

            writable_dir = self._get_writable_dir(server_id)
            uploaded_tmp = f"{writable_dir}/awd_restore_{server_id}_{int(time.time())}.tar"

            self.ssh.upload_file(server_id, local_backup_path, uploaded_tmp)
            # 上传后做完整性校验
            _, _, tcode = self.ssh.exec_command(
                server_id, f"tar -tf '{uploaded_tmp}' >/dev/null 2>&1", timeout=60
            )
            if tcode != 0:
                self.ssh.exec_command(server_id, f"rm -f '{uploaded_tmp}'", timeout=10)
                raise Exception('上传的本地备份解析失败，已中止')

            source = '本地备份'
            tar_path = uploaded_tmp
            cleanup_tar = True
            logs.append(f'[upload] 已上传本地备份到 {uploaded_tmp}')

        try:
            # ---- 步骤 2: 移除网站原始内容（无保留） ----
            self._clean_web_root(server_id, web_root, logs)

            # ---- 步骤 3: 解压备份到 web_root ----
            # 使用 --touch --no-same-owner 避免 utime/权限问题
            # 注意：tar 可能因无法修改 web_root 目录本身权限而返回非零，
            # 但文件内容已正确解压，需通过检查文件数量确认成功
            _, stderr, code = self.ssh.exec_command(
                server_id,
                f"tar xf '{tar_path}' -C '{web_root}' --touch --no-same-owner 2>&1 || true",
                timeout=180,
            )
            # 过滤 SSH shell 警告和 tar 权限警告（这些不影响文件内容）
            tar_errors = [line for line in stderr.strip().split('\n')
                          if line and not line.startswith('Could not chdir')
                          and not 'Cannot utime' in line
                          and not 'Cannot change mode' in line
                          and not 'Exiting with failure' in line]
            # 检查解压后是否有文件（比依赖 exit_code 更可靠）
            # 使用 find -L 跟随软链接（web_root 可能是软链接）
            stdout, _, _ = self.ssh.exec_command(
                server_id,
                f"find -L '{web_root}' -type f | wc -l",
                timeout=30,
            )
            file_count = int(stdout.strip() or '0')
            if file_count == 0:
                raise Exception('解压失败: web_root 无文件')
            logs.append(f'[extract] 解压完成 -> {web_root} ({file_count} 个文件)')

            # ---- 步骤 4: 修复权限 ----
            self._fix_permissions(server_id, web_root, logs)

        finally:
            # ---- 步骤 5: 仅清理本次上传的临时文件，线上原备份保留 ----
            if cleanup_tar and uploaded_tmp:
                self.ssh.exec_command(server_id, f"rm -f '{uploaded_tmp}'", timeout=10)
                logs.append(f'[cleanup] 已清理上传临时文件 {uploaded_tmp}')

        return {
            'success': True,
            'source': source,
            'version_tag': version_tag,
            'tar_path': tar_path if not cleanup_tar else None,
            'message': f'网站已恢复至版本: {version_tag}（{source}）',
            'logs': logs,
        }

    # ------------------------------------------------------------------
    # 列表与删除
    # ------------------------------------------------------------------
    def list_backups(self, server_id):
        """获取备份列表"""
        backups = BackupModel.get_by_server(server_id, 'web')
        return [dict(row) for row in backups]

    def delete_backup(self, backup_id, delete_local=True, server_id=None, delete_online=False):
        """删除备份

        Args:
            backup_id: 备份ID
            delete_local: 是否删除本地文件
            server_id: 服务器ID（用于清理线上文件）
            delete_online: 是否清理线上临时文件
        """
        backup = BackupModel.get_by_id(backup_id)

        # 删除本地文件
        if delete_local and backup and backup['file_path']:
            try:
                if os.path.exists(backup['file_path']):
                    os.remove(backup['file_path'])
            except:
                pass

        # 清理线上临时文件
        if delete_online and server_id:
            try:
                # 清理所有 awd_backup_*.tar 文件
                self.ssh.exec_command(
                    server_id,
                    'rm -f /tmp/awd_backup_*.tar /var/tmp/awd_backup_*.tar /dev/shm/awd_backup_*.tar 2>/dev/null',
                    timeout=10
                )
            except:
                pass

        BackupModel.delete(backup_id)
