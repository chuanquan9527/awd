import json
from database.db import query_db, execute_db
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import config


class UserModel:
    """用户模型"""

    @staticmethod
    def get_by_username(username):
        return query_db('SELECT * FROM users WHERE username = ?', [username], one=True)

    @staticmethod
    def get_by_id(user_id):
        return query_db('SELECT * FROM users WHERE id = ?', [user_id], one=True)

    @staticmethod
    def create(username, password):
        password_hash = generate_password_hash(password)
        return execute_db(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            [username, password_hash]
        )

    @staticmethod
    def update_password(user_id, new_password):
        password_hash = generate_password_hash(new_password)
        execute_db(
            'UPDATE users SET password_hash = ? WHERE id = ?',
            [password_hash, user_id]
        )

    @staticmethod
    def increment_login_attempts(user_id):
        execute_db(
            '''UPDATE users SET login_attempts = login_attempts + 1,
               last_attempt_time = ? WHERE id = ?''',
            [datetime.now().isoformat(), user_id]
        )

    @staticmethod
    def lock_account(user_id, minutes):
        locked_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        execute_db(
            'UPDATE users SET locked_until = ? WHERE id = ?',
            [locked_until, user_id]
        )

    @staticmethod
    def reset_login_attempts(user_id):
        execute_db(
            'UPDATE users SET login_attempts = 0, locked_until = NULL WHERE id = ?',
            [user_id]
        )

    @staticmethod
    def is_locked(user):
        if not user or not user['locked_until']:
            return False
        locked_until = datetime.fromisoformat(user['locked_until'])
        return datetime.now() < locked_until

    @staticmethod
    def verify_password(user, password):
        if not user:
            return False
        return check_password_hash(user['password_hash'], password)

    @staticmethod
    def count():
        result = query_db('SELECT COUNT(*) as count FROM users', one=True)
        return result['count'] if result else 0


class ServerModel:
    """服务器模型"""

    @staticmethod
    def get_all():
        return query_db('SELECT * FROM servers ORDER BY created_at DESC')

    @staticmethod
    def get_by_id(server_id):
        return query_db('SELECT * FROM servers WHERE id = ?', [server_id], one=True)

    @staticmethod
    def create(data):
        return execute_db('''
            INSERT INTO servers (name, host, port, username, password, server_type,
                web_root, db_name, db_user, db_password)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [
            data.get('name'), data.get('host'), data.get('port', 22),
            data.get('username'), data.get('password'), data.get('server_type', 'own'),
            data.get('web_root', '/var/www/html'), data.get('db_name', ''),
            data.get('db_user', 'root'), data.get('db_password', '')
        ])

    @staticmethod
    def update(server_id, data):
        fields = []
        values = []
        for key, value in data.items():
            fields.append(f'{key} = ?')
            values.append(value)
        values.append(server_id)
        execute_db(f'''
            UPDATE servers SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', values)

    @staticmethod
    def delete(server_id):
        execute_db('DELETE FROM servers WHERE id = ?', [server_id])

    @staticmethod
    def update_info(server_id, info):
        execute_db('''
            UPDATE servers SET
                kernel_version = ?, php_version = ?, mysql_version = ?,
                open_ports = ?, processes = ?, backdoor_users = ?,
                priv_esc_files = ?, status = 'online',
                web_root_status = ?, mysql_conn_status = ?,
                network_info = ?, system_info = ?, web_services = ?,
                db_info = ?, cache_info = ?, user_security = ?,
                cron_info = ?, writable_dirs = ?, flag_info = ?,
                port_processes = ?, security_hardening = ?, environment_info = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', [
            info.get('kernel_version', ''),
            info.get('php_version', ''),
            info.get('mysql_version', ''),
            info.get('open_ports', '[]'),
            info.get('processes', '[]'),
            info.get('backdoor_users', '[]'),
            info.get('priv_esc_files', '[]'),
            info.get('web_root_status', 'unknown'),
            info.get('mysql_conn_status', 'unknown'),
            json.dumps(info.get('network_info', {})),
            json.dumps(info.get('system_info', {})),
            json.dumps(info.get('web_services', {})),
            json.dumps(info.get('db_info', {})),
            json.dumps(info.get('cache_info', {})),
            json.dumps(info.get('user_security', {})),
            json.dumps(info.get('cron_info', {})),
            json.dumps(info.get('writable_dirs', {})),
            json.dumps(info.get('flag_info', {})),
            json.dumps(info.get('port_processes', {})),
            json.dumps(info.get('security_hardening', {})),
            json.dumps(info.get('environment_info', {})),
            server_id
        ])


class BackupModel:
    """备份模型"""

    @staticmethod
    def get_by_server(server_id, backup_type=None):
        if backup_type:
            return query_db(
                'SELECT * FROM backups WHERE server_id = ? AND backup_type = ? ORDER BY created_at DESC',
                [server_id, backup_type]
            )
        return query_db(
            'SELECT * FROM backups WHERE server_id = ? ORDER BY created_at DESC',
            [server_id]
        )

    @staticmethod
    def create(server_id, backup_type, version_tag, file_path, file_size, remote_path=None):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return execute_db('''
            INSERT INTO backups (server_id, backup_type, version_tag, file_path, file_size, remote_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', [server_id, backup_type, version_tag, file_path, file_size, remote_path, now])

    @staticmethod
    def get_by_id(backup_id):
        return query_db('SELECT * FROM backups WHERE id = ?', [backup_id], one=True)

    @staticmethod
    def delete(backup_id):
        execute_db('DELETE FROM backups WHERE id = ?', [backup_id])


class AlertModel:
    """告警模型"""

    @staticmethod
    def create(server_id, alert_type, severity, message, details=None):
        return execute_db('''
            INSERT INTO alerts (server_id, alert_type, severity, message, details)
            VALUES (?, ?, ?, ?, ?)
        ''', [server_id, alert_type, severity, message, details])

    @staticmethod
    def get_all(limit=100, unread_only=False):
        query = 'SELECT * FROM alerts'
        args = []
        if unread_only:
            query += ' WHERE is_read = 0'
        query += ' ORDER BY created_at DESC LIMIT ?'
        args.append(limit)
        return query_db(query, args)

    @staticmethod
    def mark_read(alert_id):
        execute_db('UPDATE alerts SET is_read = 1 WHERE id = ?', [alert_id])

    @staticmethod
    def get_unread_count():
        result = query_db('SELECT COUNT(*) as count FROM alerts WHERE is_read = 0', one=True)
        return result['count'] if result else 0


class MonitorConfigModel:
    """监控配置模型"""

    @staticmethod
    def get_by_server(server_id):
        return query_db('SELECT * FROM monitor_config WHERE server_id = ?', [server_id], one=True)

    @staticmethod
    def create_or_update(server_id, **kwargs):
        existing = MonitorConfigModel.get_by_server(server_id)
        if existing:
            fields = []
            values = []
            for key, value in kwargs.items():
                fields.append(f'{key} = ?')
                values.append(value)
            values.append(server_id)
            execute_db(f'''
                UPDATE monitor_config SET {', '.join(fields)} WHERE server_id = ?
            ''', values)
        else:
            execute_db('''
                INSERT INTO monitor_config (server_id, file_monitor_enabled,
                    process_monitor_enabled, traffic_monitor_enabled, monitor_interval,
                    watched_dirs, whitelist, kill_on_detect)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                server_id,
                kwargs.get('file_monitor_enabled', 0),
                kwargs.get('process_monitor_enabled', 0),
                kwargs.get('traffic_monitor_enabled', 0),
                kwargs.get('monitor_interval', 5),
                kwargs.get('watched_dirs', '[]'),
                kwargs.get('whitelist', ''),
                kwargs.get('kill_on_detect', 0)
            ])



class ScriptModel:
    """脚本部署模型"""

    @staticmethod
    def _row_to_dict(row):
        if not row:
            return None
        data = dict(row)
        try:
            files = json.loads(data.get('files') or '[]')
        except Exception:
            files = []
        data['files'] = files
        data['file_count'] = len(files)
        return data

    @staticmethod
    def get_all():
        rows = query_db('SELECT * FROM deployment_scripts ORDER BY created_at DESC')
        return [ScriptModel._row_to_dict(row) for row in rows]

    @staticmethod
    def get_by_id(script_id):
        row = query_db('SELECT * FROM deployment_scripts WHERE id = ?', [script_id], one=True)
        return ScriptModel._row_to_dict(row)

    @staticmethod
    def create(data):
        return execute_db('''
            INSERT INTO deployment_scripts (name, script_type, description, remote_dir, deploy_script, files)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', [
            data.get('name'),
            data.get('script_type'),
            data.get('description', ''),
            data.get('remote_dir') or '/tmp',
            data.get('deploy_script'),
            json.dumps(data.get('files', []), ensure_ascii=False)
        ])

    @staticmethod
    def update(script_id, data):
        allowed = {'name', 'script_type', 'description', 'remote_dir', 'deploy_script', 'files'}
        fields = []
        values = []
        for key, value in data.items():
            if key not in allowed:
                continue
            fields.append(f'{key} = ?')
            if key == 'files':
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                values.append(value)

        if not fields:
            return

        values.append(script_id)
        execute_db(f'''
            UPDATE deployment_scripts
            SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', values)

    @staticmethod
    def delete(script_id):
        execute_db('DELETE FROM deployment_scripts WHERE id = ?', [script_id])


