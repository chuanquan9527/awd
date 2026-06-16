import os
import tarfile
import json
import time
from config import WAF_STORAGE_DIR


class WAFManager:
    """WAF 管理器 - 管理本地 WAF 包和远程部署"""

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager
        os.makedirs(WAF_STORAGE_DIR, exist_ok=True)

    def list_wafs(self):
        """列出本地所有可用的 WAF 包

        每个 WAF 是 waf/ 目录下的子目录，包含 deploy.sh 和 config.json
        """
        wafs = []
        if not os.path.exists(WAF_STORAGE_DIR):
            return wafs

        for name in os.listdir(WAF_STORAGE_DIR):
            waf_dir = os.path.join(WAF_STORAGE_DIR, name)
            if not os.path.isdir(waf_dir):
                continue
            # 检查是否有 deploy.sh
            deploy_sh = os.path.join(waf_dir, 'deploy.sh')
            config_json = os.path.join(waf_dir, 'config.json')
            if not os.path.exists(deploy_sh):
                continue

            # 读取配置
            config = {}
            if os.path.exists(config_json):
                try:
                    with open(config_json, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except:
                    pass

            # 统计文件
            files = []
            for f in os.listdir(waf_dir):
                if f in ('deploy.sh', 'config.json', 'README.md'):
                    continue
                fpath = os.path.join(waf_dir, f)
                if os.path.isfile(fpath):
                    files.append(f)

            wafs.append({
                'name': name,
                'description': config.get('description', ''),
                'version': config.get('version', ''),
                'deploy_args': config.get('deploy_args', ''),
                'files': files,
                'has_config': bool(config.get('deploy_args', ''))
            })

        return wafs

    def get_waf(self, name):
        """获取指定 WAF 的详细信息"""
        waf_dir = os.path.join(WAF_STORAGE_DIR, name)
        if not os.path.isdir(waf_dir):
            return None

        deploy_sh = os.path.join(waf_dir, 'deploy.sh')
        if not os.path.exists(deploy_sh):
            return None

        config = {}
        config_json = os.path.join(waf_dir, 'config.json')
        if os.path.exists(config_json):
            try:
                with open(config_json, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except:
                pass

        # 读取 deploy.sh 内容预览
        with open(deploy_sh, 'r', encoding='utf-8') as f:
            deploy_script = f.read()

        return {
            'name': name,
            'description': config.get('description', ''),
            'version': config.get('version', ''),
            'deploy_args': config.get('deploy_args', ''),
            'deploy_script': deploy_script,
            'config': config
        }

    def deploy(self, server_id, waf_name, web_root=None, extra_args=''):
        """一键部署 WAF 到目标服务器

        流程:
        1. 将 WAF 目录打包为 tar
        2. 上传到服务器的可写入目录（如 /tmp）
        3. 解压
        4. 执行 deploy.sh
        5. 清理远程临时文件

        Args:
            server_id: 服务器ID
            waf_name: WAF名称（对应 waf/ 下的子目录名）
            web_root: 网站根目录（可选，默认使用服务器配置）
            extra_args: 额外的部署参数
        """
        from database.models import ServerModel

        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        waf_dir = os.path.join(WAF_STORAGE_DIR, waf_name)
        if not os.path.isdir(waf_dir):
            raise Exception(f'WAF "{waf_name}" 不存在')

        deploy_sh = os.path.join(waf_dir, 'deploy.sh')
        if not os.path.exists(deploy_sh):
            raise Exception(f'WAF "{waf_name}" 缺少 deploy.sh 部署脚本')

        web_root = web_root or server['web_root']
        timestamp = int(time.time())
        remote_tmp = f'/tmp/awd_waf_{timestamp}.tar'
        remote_extract_dir = f'/tmp/awd_waf_{timestamp}'

        # 步骤1: 打包 WAF 目录
        local_tar = os.path.join(WAF_STORAGE_DIR, f'_deploy_{waf_name}_{timestamp}.tar')
        try:
            with tarfile.open(local_tar, 'w') as tar:
                for item in os.listdir(waf_dir):
                    item_path = os.path.join(waf_dir, item)
                    if os.path.isfile(item_path):
                        tar.add(item_path, arcname=item)

            # 步骤2: 上传到服务器
            self.ssh.upload_file(server_id, local_tar, remote_tmp)

            # 步骤3: 解压
            self.ssh.exec_command(
                server_id,
                f'mkdir -p {remote_extract_dir} && tar xf {remote_tmp} -C {remote_extract_dir}',
                timeout=30
            )

            # 步骤4: 执行部署脚本
            # deploy.sh 参数: $1=web根目录, 后续为额外参数
            deploy_cmd = f'cd {remote_extract_dir} && chmod +x deploy.sh && bash deploy.sh {web_root}'
            if extra_args:
                deploy_cmd += f' {extra_args}'

            stdout, stderr, code = self.ssh.exec_command(server_id, deploy_cmd, timeout=120)

            result_msg = stdout or stderr or '部署完成'

            return {
                'success': True,
                'message': f'WAF "{waf_name}" 部署完成',
                'detail': result_msg,
                'waf_name': waf_name,
                'web_root': web_root
            }
        finally:
            # 步骤5: 清理
            try:
                os.remove(local_tar)
            except:
                pass
            self.ssh.exec_command(
                server_id,
                f'rm -rf {remote_tmp} {remote_extract_dir}',
                timeout=10
            )

    def undeploy(self, server_id, waf_name='', web_root=None):
        """卸载 WAF - 彻底恢复到部署前状态

        iWAF 部署后产生的变更：
        1. .[随机8位]/ 隐藏目录（WAF核心工作目录）
        2. .user.ini（auto_prepend_file 入口）
        3. .htaccess（WAF 修改了原始文件，添加了 WAF 配置）
        4. .pwaf_watcher.sh / .pwaf_watcher.pid（监控脚本）
        5. common.inc.php（WAF 生成的，覆盖/修改了原始的）
        6. 所有 PHP 文件被注入加载代码（第一行）
        7. inotifywait 守护进程
        8. /tmp 下的 waf 相关临时文件
        """
        from database.models import ServerModel

        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        web_root = web_root or server['web_root']
        steps = []

        # 步骤1: 杀死 inotifywait 守护进程和 watcher 脚本
        self.ssh.exec_command(
            server_id,
            'pkill -f "inotifywait.*pwaf" 2>/dev/null; pkill -f ".pwaf_watcher" 2>/dev/null; true',
            timeout=10
        )
        steps.append('已终止 inotifywait 守护进程')

        # 步骤2: 从 .user.ini 中提取 WAF 实际使用的隐藏目录路径
        # iWAF 可能使用容器内路径（如 /app）而非传入的 WEB_ROOT
        stdout, _, _ = self.ssh.exec_command(
            server_id,
            f'cat {web_root}/.user.ini 2>/dev/null',
            timeout=10
        )
        ini_content = stdout.strip()

        # 提取隐藏目录路径，如 /app/.5732a981
        import re
        hidden_dir_match = re.search(r'auto_prepend_file\s*=\s*(\S+)/common\.inc\.php', ini_content)
        hidden_dir = hidden_dir_match.group(1) if hidden_dir_match else None

        # 步骤3: 删除 WAF 生成的隐藏目录
        if hidden_dir:
            self.ssh.exec_command(server_id, f'rm -rf "{hidden_dir}"', timeout=10)
            steps.append(f'已删除隐藏目录: {hidden_dir}')
        else:
            # 回退：在 web_root 下搜索
            stdout, _, _ = self.ssh.exec_command(
                server_id,
                f'find {web_root} -maxdepth 1 -type d -regextype posix-extended -regex "^{web_root}/\\.[a-z0-9]{{8}}$" 2>/dev/null',
                timeout=10
            )
            for d in stdout.strip().split('\n'):
                d = d.strip()
                if d:
                    self.ssh.exec_command(server_id, f'rm -rf "{d}"', timeout=10)
                    steps.append(f'已删除隐藏目录: {d}')

        # 步骤4: 删除 .user.ini
        self.ssh.exec_command(server_id, f'rm -f {web_root}/.user.ini', timeout=10)
        steps.append('已删除 .user.ini')

        # 步骤5: 删除 .pwaf_watcher.sh 和 .pwaf_watcher.pid
        self.ssh.exec_command(
            server_id,
            f'rm -f {web_root}/.pwaf_watcher.sh {web_root}/.pwaf_watcher.pid',
            timeout=10
        )
        steps.append('已删除监控脚本')

        # 步骤6: 恢复 .htaccess（删除 WAF 添加的内容）
        # iWAF 在 .htaccess 末尾追加了 WAF 配置，需要删除这些追加内容
        # 策略: 删除包含 "Internal System Sync" 及之后的所有内容
        stdout, _, _ = self.ssh.exec_command(
            server_id,
            f'grep -n "Internal System Sync" {web_root}/.htaccess 2>/dev/null',
            timeout=10
        )
        if stdout.strip():
            # 找到 WAF 注入的起始行号，删除该行及之后的所有内容
            line_num = stdout.strip().split(':')[0]
            self.ssh.exec_command(
                server_id,
                f'sed -i \'{line_num},$d\' {web_root}/.htaccess',
                timeout=10
            )
            # 删除末尾的空行
            self.ssh.exec_command(
                server_id,
                f'sed -i -e :a -e "/^\\n*$/{{$d;N;}}" -e "ba" {web_root}/.htaccess',
                timeout=10
            )
            steps.append('已恢复 .htaccess（删除WAF配置）')
        else:
            # 如果没有 "Internal System Sync" 标记，检查是否整个文件都是 WAF 生成的
            stdout, _, _ = self.ssh.exec_command(
                server_id,
                f'grep -c "RewriteEngine" {web_root}/.htaccess 2>/dev/null',
                timeout=10
            )
            rewrite_count = int(stdout.strip() or '0')
            if rewrite_count == 0:
                # 没有原始重写规则，整个文件是 WAF 生成的
                self.ssh.exec_command(server_id, f'rm -f {web_root}/.htaccess', timeout=10)
                steps.append('已删除 .htaccess（WAF生成）')

        # 步骤7: 恢复 common.inc.php
        # iWAF 会覆盖原始的 common.inc.php，隐藏目录中有 .common.bak.php 备份
        # 注意：如果WAF没有创建备份，不应删除 common.inc.php，因为可能是原始文件
        if hidden_dir:
            bak_file = f'{hidden_dir}/.common.bak.php'
            stdout, _, _ = self.ssh.exec_command(
                server_id,
                f'test -f "{bak_file}" && echo "EXISTS" || echo "MISSING"',
                timeout=10
            )
            if stdout.strip() == 'EXISTS':
                self.ssh.exec_command(
                    server_id,
                    f'cp "{bak_file}" {web_root}/common.inc.php',
                    timeout=10
                )
                steps.append('已恢复 common.inc.php（从WAF备份）')
            else:
                # 没有WAF备份，保留当前 common.inc.php（可能是原始文件）
                # 但需要清理其中的WAF注入代码
                self.ssh.exec_command(
                    server_id,
                    f'sed -i \'1{{/@internal_handler/d}}\' {web_root}/common.inc.php 2>/dev/null',
                    timeout=10
                )
                steps.append('已清理 common.inc.php 中的WAF注入代码')

        # 步骤8: 清理所有 PHP 文件中的注入代码
        # iWAF 注入格式: <?php /* @internal_handler */ @include_once "/path/.xxxx/common.inc.php"; ?>
        # 使用 sed 删除第一行（如果包含 @internal_handler）
        self.ssh.exec_command(
            server_id,
            f'find {web_root} -name "*.php" -exec sed -i \'1{{/@internal_handler/d}}\' {{}} + 2>/dev/null',
            timeout=30
        )
        steps.append('已清理 PHP 文件中的注入代码')

        # 步骤9: 清理 /tmp 下的 waf 相关临时文件
        self.ssh.exec_command(
            server_id,
            'rm -f /tmp/waf_install.php /tmp/waf_x86_64.so /tmp/waf.php /tmp/awd_waf_* 2>/dev/null; true',
            timeout=10
        )
        steps.append('已清理 /tmp 临时文件')

        return {
            'success': True,
            'message': 'WAF 已彻底卸载',
            'steps': steps
        }

    def verify(self, server_id, web_root=None):
        """验证 WAF 部署状态"""
        from database.models import ServerModel

        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        web_root = web_root or server['web_root']

        stdout, _, _ = self.ssh.exec_command(
            server_id,
            f'cat {web_root}/.user.ini 2>/dev/null || echo "ini_missing"',
            timeout=10
        )
        ini_content = stdout.strip()

        return {
            'ini_content': ini_content,
            'is_deployed': 'auto_prepend_file' in ini_content
        }
