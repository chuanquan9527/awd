import os
import time
from datetime import datetime
from database.models import ServerModel, BackupModel
from config import BACKUP_DB_DIR, SSH_COMMAND_TIMEOUT


class DatabaseBackup:
    """数据库备份与恢复"""

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager
        os.makedirs(BACKUP_DB_DIR, exist_ok=True)

    def backup(self, server_id, version_tag, db_name=None):
        """备份数据库"""
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        db_user = server['db_user'] or 'root'
        db_pass = server['db_password'] or ''
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 构建 mysqldump 命令
        if db_name:
            dump_target = db_name
        else:
            dump_target = '--all-databases'

        remote_tmp = f'/tmp/awd_db_backup_{timestamp}.sql'
        local_filename = f'db_{server["name"]}_{version_tag}_{timestamp}.sql'
        local_path = os.path.join(BACKUP_DB_DIR, local_filename)

        # 在服务器上执行 mysqldump
        if db_pass:
            cmd = f"mysqldump -u{db_user} -p'{db_pass}' {dump_target} > {remote_tmp} 2>/dev/null"
        else:
            cmd = f"mysqldump -u{db_user} {dump_target} > {remote_tmp} 2>/dev/null"

        stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=180)

        if code != 0:
            # 尝试备选命令
            if db_pass:
                cmd = f"mysqldump -u{db_user} -p'{db_pass}' {dump_target} > {remote_tmp} 2>&1"
            else:
                cmd = f"mysqldump -u{db_user} {dump_target} > {remote_tmp} 2>&1"
            stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=180)

        # 检查远程文件
        stdout, _, _ = self.ssh.exec_command(server_id, f'stat -c %s {remote_tmp} 2>/dev/null || echo 0')
        file_size = int(stdout.strip() or '0')

        if file_size == 0:
            raise Exception('数据库备份失败，可能是密码错误或 mysqldump 不可用')

        # 下载到本地
        try:
            self.ssh.download_file(server_id, remote_tmp, local_path)
        finally:
            self.ssh.exec_command(server_id, f'rm -f {remote_tmp}', timeout=10)

        # 记录备份信息
        backup_id = BackupModel.create(
            server_id=server_id,
            backup_type='database',
            version_tag=version_tag,
            file_path=local_path,
            file_size=file_size
        )

        return {
            'backup_id': backup_id,
            'version_tag': version_tag,
            'file_path': local_path,
            'file_size': file_size
        }

    def restore(self, server_id, backup_id):
        """恢复数据库"""
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        backup = BackupModel.get_by_id(backup_id)
        if not backup:
            raise Exception('备份记录不存在')

        db_user = server['db_user'] or 'root'
        db_pass = server['db_password'] or ''
        remote_tmp = f'/tmp/awd_db_restore_{int(time.time())}.sql'

        # 上传 SQL 文件到服务器
        self.ssh.upload_file(server_id, backup['file_path'], remote_tmp)

        try:
            # 执行恢复
            if db_pass:
                cmd = f"mysql -u{db_user} -p'{db_pass}' < {remote_tmp} 2>/dev/null"
            else:
                cmd = f"mysql -u{db_user} < {remote_tmp} 2>/dev/null"

            stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=300)

            if code != 0:
                raise Exception(f'恢复失败: {stderr or stdout}')

            return {'success': True, 'message': f'数据库已恢复至版本: {backup["version_tag"]}'}
        finally:
            self.ssh.exec_command(server_id, f'rm -f {remote_tmp}', timeout=10)

    def list_backups(self, server_id):
        """获取备份列表"""
        backups = BackupModel.get_by_server(server_id, 'database')
        return [dict(row) for row in backups]

    def delete_backup(self, backup_id, delete_local=True, server_id=None, delete_online=False):
        """删除备份"""
        backup = BackupModel.get_by_id(backup_id)
        if delete_local and backup and backup['file_path']:
            try:
                if os.path.exists(backup['file_path']):
                    os.remove(backup['file_path'])
            except:
                pass
        if delete_online and server_id:
            try:
                self.ssh.exec_command(
                    server_id,
                    'rm -f /tmp/awd_db_backup_*.sql /var/tmp/awd_db_backup_*.sql 2>/dev/null',
                    timeout=10
                )
            except:
                pass
        BackupModel.delete(backup_id)
