import os
import re

# ==================== 基础配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_KEY = os.environ.get('AWD_SECRET_KEY', 'awd-defense-workbench-secret-key-2026')

# Flask 配置
FLASK_HOST = os.environ.get('AWD_HOST', '0.0.0.0')
FLASK_PORT = int(os.environ.get('AWD_PORT', 5000))
FLASK_DEBUG = os.environ.get('AWD_DEBUG', 'False').lower() == 'true'

# ==================== 管理员初始配置 ====================
# 首次启动时自动创建的管理员账户
# 生产环境请通过环境变量设置，不要硬编码弱密码
ADMIN_USERNAME = os.environ.get('AWD_ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('AWD_ADMIN_PASS', '')

# ==================== 密码策略 ====================
MIN_PASSWORD_LENGTH = 12
PASSWORD_PATTERN = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]).{12,}$'
)
PASSWORD_HINT = (
    '密码必须至少 12 位，且包含大写字母、小写字母、数字和特殊字符'
)

# 登录安全
MAX_LOGIN_ATTEMPTS = 5          # 最大连续失败次数
LOCKOUT_DURATION_MINUTES = 5    # 锁定时长（分钟）

# ==================== 数据库配置 ====================
DATABASE_PATH = os.path.join(BASE_DIR, 'database', 'awd.db')

# ==================== SSH 配置 ====================
SSH_DEFAULT_PORT = 22
SSH_CONNECT_TIMEOUT = 10        # SSH 连接超时（秒）
SSH_COMMAND_TIMEOUT = 60        # SSH 命令执行超时（秒）
SSH_MAX_RETRIES = 3             # 连接失败最大重试次数
SSH_RETRY_DELAY = 2             # 重试间隔（秒）

# ==================== 备份配置 ====================
BACKUP_WEB_DIR = os.path.join(BASE_DIR, 'backups', 'web')
BACKUP_DB_DIR = os.path.join(BASE_DIR, 'backups', 'database')
BACKUP_MAX_SIZE_MB = 500        # 单个备份最大大小（MB）

# ==================== WAF 配置 ====================
WAF_STORAGE_DIR = os.path.join(BASE_DIR, 'waf')       # WAF包存储目录
WAF_UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
WAF_DEFAULT_FILE = 'waf.php'
WAF_INI_FILE = '.user.ini'
WAF_FILE_PERMISSIONS = 0o444    # 只读权限

# ==================== 监控配置 ====================
MONITOR_DEFAULT_INTERVAL = 5    # 默认监控间隔（秒）
MONITOR_MIN_INTERVAL = 2        # 最小监控间隔（秒）
MONITOR_MAX_INTERVAL = 300      # 最大监控间隔（秒）

# 文件监控
FILE_MONITOR_WATCHED_DIRS = ['/var/www/html']

# 进程监控
PROCESS_MONITOR_SUSPICIOUS_PATTERNS = [
    r'php.*while.*true',
    r'bash\s+-i',
    r'nc\s+.*-e',
    r'python.*socket',
    r'perl.*socket',
    r'crontab',
]

# 流量监控
TRAFFIC_LOG_PATHS = {
    'apache': '/var/log/apache2/access.log',
    'nginx': '/var/log/nginx/access.log',
}

# 预置流量监控规则
DEFAULT_TRAFFIC_RULES = [
    {
        'rule_name': 'Flag读取检测',
        'pattern': r'(?i)(flag|getflag|readflag|cat\s+/flag)',
        'severity': 'critical',
        'description': '检测到请求中包含 flag 相关关键词，可能是对手在尝试读取 flag',
    },
    {
        'rule_name': 'SQL注入检测',
        'pattern': r'(?i)(union\s+select|information_schema|into\s+outfile|load_file)',
        'severity': 'critical',
        'description': '检测到 SQL 注入攻击特征',
    },
    {
        'rule_name': '命令执行检测',
        'pattern': r'(?i)(system\s*\(|exec\s*\(|passthru\s*\(|shell_exec\s*\(|eval\s*\()',
        'severity': 'critical',
        'description': '检测到命令执行攻击特征',
    },
    {
        'rule_name': '目录穿越检测',
        'pattern': r'(\.\./|\.\.\\|%2e%2e%2f|%252e%252e%252f)',
        'severity': 'warning',
        'description': '检测到目录穿越攻击特征',
    },
    {
        'rule_name': 'Webshell访问检测',
        'pattern': r'(?i)(shell\.php|cmd\.php|c99\.php|r57\.php|backdoor|webshell)',
        'severity': 'critical',
        'description': '检测到可能的 webshell 文件访问',
    },
]

# ==================== 资源探测配置 ====================
PROBE_DEFAULT_THREADS = 50      # 默认探测线程数
PROBE_DEFAULT_TIMEOUT = 5       # 默认探测超时（秒）
PROBE_DEFAULT_PORTS = [80, 8080, 443]  # 默认探测端口
