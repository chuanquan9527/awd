import os
import re
import time
from datetime import datetime
from database.models import ServerModel, BackupModel
from config import BACKUP_DB_DIR, SSH_COMMAND_TIMEOUT


class DatabaseBackup:
    """数据库备份与恢复 - 与网站备份策略保持一致"""

    # 候选可写入目录（按优先级排序）
    CANDIDATE_DIRS = ['/tmp', '/var/tmp', '/dev/shm', '/var/www/html', '/var/www', '/home']

    # version_tag 白名单：仅允许字母、数字、点、下划线、短横线
    _TAG_RE = re.compile(r'^[A-Za-z0-9._-]+$')

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager
        os.makedirs(BACKUP_DB_DIR, exist_ok=True)

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
        """在远端按 version_tag 精确匹配可用 SQL 文件，返回路径或 None。

        匹配规则：awd_db_backup_<server_id>_<safe_tag>_*.sql
        - 完整精确通配，避免子串误命中
        - 排除 0 字节残留
        - 取 mtime 最新
        """
        safe_tag = self._sanitize_tag(version_tag)
        pattern = f'awd_db_backup_{server_id}_{safe_tag}_*.sql'
        # 使用完整的候选目录列表（与备份时可选择的目录一致）
        for d in self.CANDIDATE_DIRS:
            cmd = (
                f"find '{d}' -maxdepth 1 -type f -name '{pattern}' "
                f"-size +0c -printf '%T@ %p\\n' 2>/dev/null "
                f"| sort -rn | head -1 | awk '{{print $2}}'"
            )
            stdout, _, code = self.ssh.exec_command(server_id, cmd, timeout=10)
            path = stdout.strip()
            if code == 0 and path:
                return path
        return None

    # ------------------------------------------------------------------
    # 备份
    # ------------------------------------------------------------------
    def backup(self, server_id, version_tag, db_name=None, storage_dir=None, clean_remote=False):
        """备份数据库

        Args:
            server_id: 服务器ID
            version_tag: 版本标签（白名单校验）
            db_name: 数据库名（None=全库备份）
            storage_dir: 存储目录（默认/tmp，可选择可写入目录）
            clean_remote: 下载完成后是否移除线上临时文件（默认False，不删除，便于复用）
        """
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        safe_tag = self._sanitize_tag(version_tag)

        db_user = server['db_user'] or 'root'
        db_pass = server['db_password'] or ''
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 确定存储目录
        if not storage_dir:
            storage_dir = '/tmp'

        # 确定备份目标
        if db_name:
            dump_target = db_name
        else:
            dump_target = '--all-databases'

        # 远端命名包含 server_id + safe_tag，方便 restore 精确匹配
        remote_tmp = f"{storage_dir}/awd_db_backup_{server_id}_{safe_tag}_{timestamp}.sql"
        local_filename = f'db_{server["name"]}_{safe_tag}_{timestamp}.sql'
        local_path = os.path.join(BACKUP_DB_DIR, local_filename)

        # 在服务器上执行 mysqldump
        # 使用单引号包裹密码，避免特殊字符问题
        if db_pass:
            cmd = f"mysqldump -u'{db_user}' -p'{db_pass}' {dump_target} > '{remote_tmp}' 2>/dev/null"
        else:
            cmd = f"mysqldump -u'{db_user}' {dump_target} > '{remote_tmp}' 2>/dev/null"

        stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=180)

        # 失败时尝试备选命令（输出错误信息以便诊断）
        if code != 0:
            if db_pass:
                cmd = f"mysqldump -u'{db_user}' -p'{db_pass}' {dump_target} > '{remote_tmp}' 2>&1"
            else:
                cmd = f"mysqldump -u'{db_user}' {dump_target} > '{remote_tmp}' 2>&1"
            stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=180)

        # 检查远程文件是否存在且大小 > 0
        stdout, _, _ = self.ssh.exec_command(server_id, f"stat -c %s '{remote_tmp}' 2>/dev/null || echo 0")
        file_size = int(stdout.strip() or '0')

        if file_size == 0:
            raise Exception('数据库备份失败: 备份文件大小为0，可能是密码错误或 mysqldump 不可用')

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

        # 记录备份信息（包含线上路径，恢复时直接使用）
        backup_id = BackupModel.create(
            server_id=server_id,
            backup_type='database',
            version_tag=safe_tag,
            file_path=local_path,
            file_size=file_size,
            remote_path=remote_tmp if not clean_remote else None
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
        """恢复数据库 - 智能策略（优先使用线上备份）

        恢复策略（优化版）：
        1. 前置校验（server / backup 记录）
        2. 解析 SQL 来源：
           - 优先使用备份记录中的 remote_path（直接读取，无需搜索）
           - 若 remote_path 无效，再在远端按 version_tag 精确匹配
           - 若线上无匹配，则上传本地备份
        3. 执行 mysql 导入（SQL 中已有 DROP TABLE IF EXISTS，无需额外清空）
        4. 清理本次上传的临时文件（线上原备份保留以便复用）
        """
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        backup = BackupModel.get_by_id(backup_id)
        if not backup:
            raise Exception('备份记录不存在')

        db_user = server['db_user'] or 'root'
        db_pass = server['db_password'] or ''
        version_tag = backup['version_tag']
        local_backup_path = backup['file_path']
        stored_remote_path = backup['remote_path']  # 备份时记录的线上路径
        logs = []

        # ---- 步骤 1: 解析 SQL 来源（优先使用记录的 remote_path） ----
        uploaded_tmp = None  # 仅本次上传的临时文件需要在最后清理

        # 优先使用备份时记录的线上路径
        if stored_remote_path:
            # 校验线上文件是否仍然存在且有效
            stdout, _, code = self.ssh.exec_command(
                server_id, f"test -f '{stored_remote_path}' && stat -c %s '{stored_remote_path}' 2>/dev/null || echo 0",
                timeout=10
            )
            file_size = int(stdout.strip() or '0')
            if code == 0 and file_size > 0:
                logs.append(f'[source] 使用记录的线上备份: {stored_remote_path}')
                source = '线上备份'
                sql_path = stored_remote_path
                cleanup_sql = False
            else:
                logs.append(f'[source] 记录的线上备份不存在，尝试重新查找')
                stored_remote_path = None  # 标记无效，走后续流程

        # 若记录的路径无效，尝试在远端搜索匹配
        if not stored_remote_path:
            try:
                remote_sql = self._find_remote_backup(server_id, version_tag)
            except Exception as e:
                remote_sql = None

            if remote_sql:
                logs.append(f'[source] 命中线上备份: {remote_sql}')
                source = '线上备份'
                sql_path = remote_sql
                cleanup_sql = False
            else:
                logs.append('[source] 线上无匹配，回退本地上传')
                if not local_backup_path or not os.path.exists(local_backup_path):
                    raise Exception('线上无对应版本，且本地备份文件不存在，无法恢复')

                writable_dir = self._get_writable_dir(server_id)
                uploaded_tmp = f"{writable_dir}/awd_db_restore_{server_id}_{int(time.time())}.sql"

                self.ssh.upload_file(server_id, local_backup_path, uploaded_tmp)
                # 校验上传文件大小
                stdout, _, _ = self.ssh.exec_command(
                    server_id, f"stat -c %s '{uploaded_tmp}' 2>/dev/null || echo 0"
                )
                file_size = int(stdout.strip() or '0')
                if file_size == 0:
                    self.ssh.exec_command(server_id, f"rm -f '{uploaded_tmp}'", timeout=10)
                    raise Exception('上传的本地备份文件大小为0，已中止')

                source = '本地备份'
                sql_path = uploaded_tmp
                cleanup_sql = True
                logs.append(f'[upload] 已上传本地备份到 {uploaded_tmp}')

        try:
            # ---- 步骤 2: 执行恢复 ----
            # mysqldump 生成的 SQL 已包含 DROP TABLE IF EXISTS，无需额外清空
            if db_pass:
                cmd = f"mysql -u'{db_user}' -p'{db_pass}' < '{sql_path}' 2>&1"
            else:
                cmd = f"mysql -u'{db_user}' < '{sql_path}' 2>&1"

            stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=300)

            # 过滤 SSH shell 警告
            mysql_errors = [line for line in stderr.strip().split('\n')
                            if line and not line.startswith('Could not chdir')]

            if code != 0 and mysql_errors:
                raise Exception(f'恢复失败: {mysql_errors[0]}')

            logs.append(f'[restore] 数据库已恢复 -> {version_tag}')

        finally:
            # ---- 步骤 3: 仅清理本次上传的临时文件，线上原备份保留 ----
            if cleanup_sql and uploaded_tmp:
                self.ssh.exec_command(server_id, f"rm -f '{uploaded_tmp}'", timeout=10)
                logs.append(f'[cleanup] 已清理上传临时文件 {uploaded_tmp}')

        return {
            'success': True,
            'source': source,
            'version_tag': version_tag,
            'sql_path': sql_path if not cleanup_sql else None,
            'message': f'数据库已恢复至版本: {version_tag}（{source}）',
            'logs': logs,
        }

    # ------------------------------------------------------------------
    # 列表与删除
    # ------------------------------------------------------------------
    def list_backups(self, server_id):
        """获取备份列表"""
        backups = BackupModel.get_by_server(server_id, 'database')
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
                # 清理所有 awd_db_backup_*.sql 文件
                self.ssh.exec_command(
                    server_id,
                    'rm -f /tmp/awd_db_backup_*.sql /var/tmp/awd_db_backup_*.sql /dev/shm/awd_db_backup_*.sql 2>/dev/null',
                    timeout=10
                )
            except:
                pass

        BackupModel.delete(backup_id)