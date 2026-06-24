import sqlite3
import os
from contextlib import contextmanager
from config import DATABASE_PATH


def init_db():
    """初始化数据库，创建所有表"""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # users 表 - 工作台用户
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            login_attempts INTEGER DEFAULT 0,
            last_attempt_time TIMESTAMP,
            locked_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # servers 表 - 服务器信息（扩展字段支持详细信息采集）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER DEFAULT 22,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            server_type TEXT DEFAULT 'own',
            web_root TEXT DEFAULT '/var/www/html',
            db_name TEXT DEFAULT '',
            db_user TEXT DEFAULT 'root',
            db_password TEXT DEFAULT '',
            status TEXT DEFAULT 'offline',
            kernel_version TEXT,
            php_version TEXT,
            mysql_version TEXT,
            open_ports TEXT,
            processes TEXT,
            backdoor_users TEXT,
            priv_esc_files TEXT,
            web_root_status TEXT DEFAULT 'unknown',
            mysql_conn_status TEXT DEFAULT 'unknown',
            -- 扩展字段：详细服务器信息（JSON格式存储）
            network_info TEXT,
            system_info TEXT,
            web_services TEXT,
            db_info TEXT,
            cache_info TEXT,
            user_security TEXT,
            cron_info TEXT,
            writable_dirs TEXT,
            flag_info TEXT,
            port_processes TEXT,
            security_hardening TEXT,
            environment_info TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # backups 表 - 备份记录（新增 remote_path 字段）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            backup_type TEXT NOT NULL,
            version_tag TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            remote_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
        )
    ''')

    # 为已存在的 backups 表添加 remote_path 字段（兼容旧数据）
    try:
        cursor.execute('ALTER TABLE backups ADD COLUMN remote_path TEXT')
    except sqlite3.OperationalError:
        pass  # 字段已存在，忽略

    # file_baselines 表 - 文件基线
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            md5_hash TEXT NOT NULL,
            file_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
            UNIQUE(server_id, file_path)
        )
    ''')

    # alerts 表 - 告警记录
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER,
            alert_type TEXT NOT NULL,
            severity TEXT DEFAULT 'warning',
            message TEXT NOT NULL,
            details TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL
        )
    ''')

    # monitor_config 表 - 监控配置
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS monitor_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL UNIQUE,
            file_monitor_enabled INTEGER DEFAULT 0,
            process_monitor_enabled INTEGER DEFAULT 0,
            traffic_monitor_enabled INTEGER DEFAULT 0,
            monitor_interval INTEGER DEFAULT 5,
            watched_dirs TEXT,
            whitelist TEXT,
            kill_on_detect INTEGER DEFAULT 0,
            FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
        )
    ''')
    
    # 检查是否需要添加 whitelist 字段（兼容旧数据库）
    try:
        cursor.execute('SELECT whitelist FROM monitor_config LIMIT 1')
    except:
        cursor.execute('ALTER TABLE monitor_config ADD COLUMN whitelist TEXT')

    # deployment_scripts 表 - 脚本部署配置
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deployment_scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            script_type TEXT NOT NULL,
            description TEXT DEFAULT '',
            remote_dir TEXT NOT NULL DEFAULT '/tmp',
            deploy_script TEXT NOT NULL,
            files TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 兼容旧数据：若表已存在但缺少 remote_dir 字段，则补充默认值
    try:
        cursor.execute('SELECT remote_dir FROM deployment_scripts LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE deployment_scripts ADD COLUMN remote_dir TEXT NOT NULL DEFAULT '/tmp'")

    conn.commit()
    conn.close()


@contextmanager
def get_db():
    """获取数据库连接的上下文管理器"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def query_db(query, args=(), one=False):
    """执行查询"""
    with get_db() as conn:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        cur.close()
        return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    """执行写入操作，返回最后插入的 ID"""
    with get_db() as conn:
        cur = conn.execute(query, args)
        conn.commit()
        last_id = cur.lastrowid
        cur.close()
        return last_id
