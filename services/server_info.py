import json
import threading


class ServerInfoCollector:
    """服务器信息采集器 - 参考 awd_info_collect.sh 脚本实现"""

    # 已知合法的 SUID 文件白名单
    LEGIT_SUID_FILES = {
        '/usr/bin/sudo', '/usr/bin/passwd', '/usr/bin/chsh', '/usr/bin/chfn',
        '/usr/bin/newgrp', '/usr/bin/gpasswd', '/usr/bin/pkexec',
        '/usr/lib/dbus-1.0/dbus-daemon-launch-helper',
        '/usr/lib/policykit-1/polkit-agent-helper-1',
        '/usr/lib/openssh/ssh-keysign',
        '/bin/su', '/bin/mount', '/bin/umount', '/bin/ping', '/bin/ping6',
        '/usr/sbin/pppd',
    }

    # 已知合法的系统用户
    LEGIT_USERS = {'root', 'daemon', 'bin', 'sys', 'sync', 'games', 'man',
                   'lp', 'mail', 'news', 'uucp', 'proxy', 'www-data', 'backup',
                   'list', 'irc', 'gnats', 'nobody', 'systemd-network',
                   'systemd-resolve', 'messagebus', 'sshd'}

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager

    def collect_all(self, server_id):
        """串行采集所有基础服务器信息（SSH连接不支持并发exec_command）"""
        tasks = {
            'kernel_version': self._get_kernel_version,
            'php_version': self._get_php_version,
            'mysql_version': self._get_mysql_version,
            'open_ports': self._get_open_ports,
            'processes': self._get_processes,
            'backdoor_users': self._get_backdoor_users,
            'priv_esc_files': self._get_priv_esc_files,
        }

        results = {}
        for key, func in tasks.items():
            try:
                results[key] = func(server_id)
            except Exception as e:
                results[key] = self._default_value(key)

        return results

    def collect_detailed_info(self, server_id):
        """串行采集详细的服务器信息（SSH连接不支持并发exec_command）"""
        detail_tasks = {
            'network_info': self._collect_network_info,
            'system_info': self._collect_system_info,
            'web_services': self._collect_web_services,
            'db_info': self._collect_db_info,
            'cache_info': self._collect_cache_info,
            'user_security': self._collect_user_security,
            'cron_info': self._collect_cron_info,
            'writable_dirs': self._collect_writable_dirs,
            'flag_info': self._collect_flag_info,
            'port_processes': self._collect_port_processes,
            'security_hardening': self._collect_security_hardening,
            'environment_info': self._collect_environment_info,
        }

        results = {}
        for key, func in detail_tasks.items():
            try:
                results[key] = func(server_id)
            except Exception as e:
                results[key] = {'error': str(e)}

        return results

    def check_web_root(self, server_id, web_root):
        """检查网站根目录是否可用"""
        if not web_root:
            return 'unknown'
        stdout, stderr, rc = self.ssh.exec_command(
            server_id,
            f"test -d '{web_root}' && echo 'EXISTS' || echo 'NOT_FOUND'"
        )
        if rc == 0 and stdout and 'EXISTS' in stdout:
            # 进一步检查是否有读写权限
            stdout2, _, rc2 = self.ssh.exec_command(
                server_id,
                f"test -r '{web_root}' && test -w '{web_root}' && echo 'RW' || echo 'NO_RW'"
            )
            if rc2 == 0 and stdout2 and 'RW' in stdout2:
                return 'available'
            return 'readonly'
        return 'unavailable'

    def check_mysql_connection(self, server_id, db_user, db_password, db_name=''):
        """检查 MySQL 连接是否可用"""
        if not db_user or not db_password:
            return 'not_configured'
        db_param = f" -D '{db_name}'" if db_name else ""
        cmd = (
            f"mysql -u '{db_user}' -p'{db_password}'{db_param} "
            f"-e 'SELECT 1;' 2>/dev/null && echo 'OK' || echo 'FAIL'"
        )
        stdout, stderr, rc = self.ssh.exec_command(server_id, cmd)
        if stdout and 'OK' in stdout:
            return 'available'
        return 'unavailable'

    # ==================== 详细信息采集方法 ====================

    def _collect_network_info(self, server_id):
        """1. 网络信息"""
        info = {}
        # IP地址
        stdout, _, _ = self.ssh.exec_command(server_id, "ip -4 addr show 2>/dev/null | grep -oP 'inet \\K[\\d.]+' | grep -v '127.0.0.1'")
        info['ip_addresses'] = [ip.strip() for ip in stdout.split('\n') if ip.strip()] if stdout else []
        # 网段
        stdout, _, _ = self.ssh.exec_command(server_id, "ip -4 addr show 2>/dev/null | grep -oP 'inet \\K[\\d.]+/[\\d]+' | grep -v '127.0.0.1'")
        info['network_segments'] = [s.strip() for s in stdout.split('\n') if s.strip()] if stdout else []
        # 路由
        stdout, _, _ = self.ssh.exec_command(server_id, "ip route 2>/dev/null | grep default || route -n 2>/dev/null | grep '^0.0.0.0'")
        info['routes'] = stdout.strip() if stdout else ''
        # DNS
        stdout, _, _ = self.ssh.exec_command(server_id, "cat /etc/resolv.conf 2>/dev/null")
        info['dns'] = stdout.strip() if stdout else ''
        # hosts
        stdout, _, _ = self.ssh.exec_command(server_id, "cat /etc/hosts 2>/dev/null")
        info['hosts'] = stdout.strip() if stdout else ''
        # ARP
        stdout, _, _ = self.ssh.exec_command(server_id, "ip neigh 2>/dev/null || arp -a 2>/dev/null")
        info['arp'] = stdout.strip() if stdout else ''
        return info

    def _collect_system_info(self, server_id):
        """2. 系统信息"""
        info = {}
        stdout, _, _ = self.ssh.exec_command(server_id, 'uname -s && uname -n && uname -r && uname -m')
        lines = stdout.split('\n') if stdout else []
        info['kernel_name'] = lines[0] if len(lines) > 0 else ''
        info['hostname'] = lines[1] if len(lines) > 1 else ''
        info['kernel_version'] = lines[2] if len(lines) > 2 else ''
        info['architecture'] = lines[3] if len(lines) > 3 else ''
        # 发行版
        stdout, _, _ = self.ssh.exec_command(server_id, 'cat /etc/os-release 2>/dev/null || cat /etc/redhat-release 2>/dev/null')
        info['os_release'] = stdout.strip() if stdout else ''
        # lsb_release
        stdout, _, _ = self.ssh.exec_command(server_id, 'lsb_release -a 2>/dev/null')
        info['lsb_release'] = stdout.strip() if stdout else ''
        # /proc/version
        stdout, _, _ = self.ssh.exec_command(server_id, 'cat /proc/version 2>/dev/null')
        info['proc_version'] = stdout.strip() if stdout else ''
        return info

    def _collect_web_services(self, server_id):
        """3&4&5. Web服务信息（PHP、Apache、Nginx）"""
        info = {}
        # PHP
        stdout, _, _ = self.ssh.exec_command(server_id, 'php -v 2>/dev/null | head -1')
        info['php_version'] = stdout.strip() if stdout else '未安装'
        stdout, _, _ = self.ssh.exec_command(server_id, 'php --ini 2>/dev/null | head -20')
        info['php_ini'] = stdout.strip() if stdout else ''
        stdout, _, _ = self.ssh.exec_command(server_id, 'php -m 2>/dev/null')
        info['php_modules'] = stdout.strip() if stdout else ''
        # PHP安全配置
        stdout, _, _ = self.ssh.exec_command(server_id, "php -r 'foreach([\"disable_functions\",\"disable_classes\",\"open_basedir\",\"allow_url_fopen\",\"allow_url_include\",\"display_errors\",\"expose_php\",\"upload_max_filesize\",\"post_max_size\",\"max_execution_time\",\"memory_limit\",\"session.save_path\",\"extension_dir\",\"error_log\",\"log_errors\"] as \$k) echo sprintf(\"%-25s => %s\\n\", \$k, ini_get(\$k));' 2>/dev/null")
        info['php_security'] = stdout.strip() if stdout else ''

        # Apache
        stdout, _, _ = self.ssh.exec_command(server_id, 'apache2 -v 2>/dev/null || httpd -v 2>/dev/null')
        info['apache_version'] = stdout.strip() if stdout else '未安装'
        stdout, _, _ = self.ssh.exec_command(server_id, 'ls -la /var/log/apache2 2>/dev/null || ls -la /var/log/httpd 2>/dev/null')
        info['apache_logs'] = stdout.strip() if stdout else ''

        # Nginx
        stdout, _, _ = self.ssh.exec_command(server_id, 'nginx -v 2>&1')
        info['nginx_version'] = stdout.strip() if stdout else '未安装'
        stdout, _, _ = self.ssh.exec_command(server_id, 'ls -la /var/log/nginx 2>/dev/null')
        info['nginx_logs'] = stdout.strip() if stdout else ''

        return info

    def _collect_db_info(self, server_id):
        """6. 数据库信息"""
        info = {}
        stdout, _, _ = self.ssh.exec_command(server_id, 'mysql --version 2>/dev/null || mariadb --version 2>/dev/null')
        info['mysql_version'] = stdout.strip() if stdout else '未安装'
        stdout, _, _ = self.ssh.exec_command(server_id, 'which mysql 2>/dev/null; which mysqld 2>/dev/null')
        info['mysql_paths'] = stdout.strip() if stdout else ''
        # 数据目录
        stdout, _, _ = self.ssh.exec_command(server_id, 'ls -la /var/lib/mysql 2>/dev/null | head -10')
        info['mysql_datadir'] = stdout.strip() if stdout else ''
        # bind-address
        stdout, _, _ = self.ssh.exec_command(server_id, "grep -i 'bind-address' /etc/mysql/my.cnf /etc/my.cnf 2>/dev/null")
        info['mysql_bind'] = stdout.strip() if stdout else '未配置'
        # 弱密码检测
        info['weak_passwords'] = []
        for pwd in ['', 'root', 'admin', '123456', 'password']:
            if pwd:
                cmd = f"echo 'exit' | mysql -u root -p'{pwd}' 2>/dev/null && echo 'OK:{pwd}'"
            else:
                cmd = "echo 'exit' | mysql -u root 2>/dev/null && echo 'OK:empty'"
            stdout, _, _ = self.ssh.exec_command(server_id, cmd)
            if stdout and 'OK:' in stdout:
                info['weak_passwords'].append(stdout.strip().replace('OK:', ''))
        return info

    def _collect_cache_info(self, server_id):
        """7. 缓存服务信息（Redis）"""
        info = {}
        stdout, _, _ = self.ssh.exec_command(server_id, 'redis-cli --version 2>/dev/null || redis-server --version 2>/dev/null')
        info['redis_version'] = stdout.strip() if stdout else '未安装'
        # 未授权检测
        stdout, _, _ = self.ssh.exec_command(server_id, 'redis-cli -h 127.0.0.1 -p 6379 --no-auth-warning info 2>/dev/null | head -5')
        info['redis_unauth'] = '存在未授权' if stdout and 'redis_version' in stdout else '需要认证或未运行'
        # 配置文件
        stdout, _, _ = self.ssh.exec_command(server_id, "grep -E '^(bind|port|requirepass|protected-mode)' /etc/redis/redis.conf /etc/redis.conf 2>/dev/null")
        info['redis_config'] = stdout.strip() if stdout else ''
        return info

    def _collect_user_security(self, server_id):
        """8. 用户安全检查"""
        info = {}
        stdout, _, _ = self.ssh.exec_command(server_id, 'cat /etc/passwd 2>/dev/null')
        info['passwd_content'] = stdout.strip() if stdout else ''
        # 可登录用户
        stdout, _, _ = self.ssh.exec_command(server_id, "grep -vE '(/nologin|/false|/sync|/shutdown|/halt)' /etc/passwd 2>/dev/null")
        info['login_users'] = stdout.strip() if stdout else ''
        # UID=0用户
        stdout, _, _ = self.ssh.exec_command(server_id, "awk -F: '$3 == 0 {print $0}' /etc/passwd 2>/dev/null")
        info['uid0_users'] = stdout.strip() if stdout else ''
        # shadow可读性
        stdout, _, _ = self.ssh.exec_command(server_id, 'cat /etc/shadow 2>/dev/null | head -3')
        info['shadow_readable'] = '可读' if stdout and ':' in stdout else '不可读'
        # sudo权限
        stdout, _, _ = self.ssh.exec_command(server_id, 'sudo -l 2>/dev/null')
        info['sudo_privs'] = stdout.strip() if stdout else '无法获取'
        return info

    def _collect_cron_info(self, server_id):
        """9. 定时任务信息"""
        info = {}
        stdout, _, _ = self.ssh.exec_command(server_id, 'cat /etc/crontab 2>/dev/null')
        info['system_crontab'] = stdout.strip() if stdout else ''
        stdout, _, _ = self.ssh.exec_command(server_id, 'ls -la /etc/cron.d/ 2>/dev/null')
        info['cron_d'] = stdout.strip() if stdout else ''
        stdout, _, _ = self.ssh.exec_command(server_id, 'ls -la /etc/cron.daily/ /etc/cron.hourly/ /etc/cron.weekly/ 2>/dev/null')
        info['cron_period'] = stdout.strip() if stdout else ''
        stdout, _, _ = self.ssh.exec_command(server_id, 'crontab -l 2>/dev/null')
        info['user_crontab'] = stdout.strip() if stdout else ''
        return info

    def _collect_writable_dirs(self, server_id):
        """10. 可写入目录探测"""
        info = {}
        dirs_to_check = ['/var/www/html', '/tmp', '/var/tmp', '/dev/shm', '/home', '/var/www']
        writable = []
        for d in dirs_to_check:
            stdout, _, _ = self.ssh.exec_command(server_id, f"test -w '{d}' 2>/dev/null && echo 'WRITABLE:{d}' || echo 'NO:{d}'")
            if stdout and 'WRITABLE:' in stdout:
                writable.append(d)
        info['writable_dirs'] = writable
        # Web目录实际路径
        stdout, _, _ = self.ssh.exec_command(server_id, 'ls -la /var/www/html 2>/dev/null | head -5')
        info['web_root_content'] = stdout.strip() if stdout else ''
        return info

    def _collect_flag_info(self, server_id):
        """11. Flag信息探测"""
        info = {}
        stdout, _, _ = self.ssh.exec_command(server_id, 'cat /flag 2>/dev/null')
        if stdout:
            info['flag_exists'] = True
            info['flag_content'] = stdout.strip()
        else:
            info['flag_exists'] = False
            info['flag_content'] = ''
        # 搜索flag文件
        stdout, _, _ = self.ssh.exec_command(server_id, 'find / -maxdepth 4 -name "flag" -o -name "flag.txt" 2>/dev/null | head -5')
        info['flag_files'] = [f.strip() for f in stdout.split('\n') if f.strip()] if stdout else []
        # 进程中的flag
        stdout, _, _ = self.ssh.exec_command(server_id, 'ps aux 2>/dev/null | grep -i flag | grep -v grep')
        info['flag_processes'] = stdout.strip() if stdout else ''
        return info

    def _collect_port_processes(self, server_id):
        """12&13. 开放端口和进程"""
        info = {}
        stdout, _, _ = self.ssh.exec_command(server_id, 'ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null')
        info['listening_ports'] = stdout.strip() if stdout else ''
        stdout, _, _ = self.ssh.exec_command(server_id, 'ps aux 2>/dev/null')
        info['processes'] = stdout.strip() if stdout else ''
        stdout, _, _ = self.ssh.exec_command(server_id, 'pstree -ap 2>/dev/null || echo "pstree未安装"')
        info['process_tree'] = stdout.strip() if stdout else ''
        return info

    def _collect_security_hardening(self, server_id):
        """BONUS: 安全加固信息"""
        info = {}
        # SUID文件
        stdout, _, _ = self.ssh.exec_command(server_id, 'find / -perm -4000 -type f 2>/dev/null | head -30')
        info['suid_files'] = [f.strip() for f in stdout.split('\n') if f.strip()] if stdout else []
        # SGID文件
        stdout, _, _ = self.ssh.exec_command(server_id, 'find / -perm -2000 -type f 2>/dev/null | head -20')
        info['sgid_files'] = [f.strip() for f in stdout.split('\n') if f.strip()] if stdout else []
        # iptables
        stdout, _, _ = self.ssh.exec_command(server_id, 'iptables -L -n 2>/dev/null | head -20')
        info['iptables'] = stdout.strip() if stdout else '无法读取'
        # ASLR
        stdout, _, _ = self.ssh.exec_command(server_id, 'cat /proc/sys/kernel/randomize_va_space 2>/dev/null')
        info['aslr'] = stdout.strip() if stdout else '未知'
        # SELinux/AppArmor
        stdout, _, _ = self.ssh.exec_command(server_id, 'getenforce 2>/dev/null || aa-status 2>/dev/null | head -3')
        info['mac'] = stdout.strip() if stdout else '未安装'
        return info

    def _collect_environment_info(self, server_id):
        """BONUS: 环境信息"""
        info = {}
        # 容器检测
        stdout, _, _ = self.ssh.exec_command(server_id, 'test -f /.dockerenv && echo "Docker容器" || echo "非Docker"')
        info['container'] = stdout.strip() if stdout else '未知'
        # 编程语言
        stdout, _, _ = self.ssh.exec_command(server_id, 'python --version 2>&1 || python3 --version 2>&1')
        info['python_version'] = stdout.strip() if stdout else '未安装'
        stdout, _, _ = self.ssh.exec_command(server_id, 'gcc --version 2>/dev/null | head -1')
        info['gcc_version'] = stdout.strip() if stdout else '未安装'
        # 磁盘
        stdout, _, _ = self.ssh.exec_command(server_id, 'df -h 2>/dev/null')
        info['disk'] = stdout.strip() if stdout else ''
        # 内存
        stdout, _, _ = self.ssh.exec_command(server_id, 'free -h 2>/dev/null || cat /proc/meminfo 2>/dev/null | head -5')
        info['memory'] = stdout.strip() if stdout else ''
        # CPU
        stdout, _, _ = self.ssh.exec_command(server_id, 'lscpu 2>/dev/null | head -10')
        info['cpu'] = stdout.strip() if stdout else ''
        # 环境变量
        stdout, _, _ = self.ssh.exec_command(server_id, 'env 2>/dev/null')
        info['env'] = stdout.strip() if stdout else ''
        # Web根目录文件
        stdout, _, _ = self.ssh.exec_command(server_id, 'ls -la /var/www/html 2>/dev/null | head -20')
        info['web_files'] = stdout.strip() if stdout else ''
        return info

    # ==================== 原有基础采集方法 ====================

    def _default_value(self, key):
        """获取默认值"""
        list_keys = ['open_ports', 'processes', 'backdoor_users', 'priv_esc_files']
        return '[]' if key in list_keys else ''

    def _get_kernel_version(self, server_id):
        """获取内核版本"""
        stdout, _, _ = self.ssh.exec_command(server_id, 'uname -r')
        return stdout or '未知'

    def _get_php_version(self, server_id):
        """获取 PHP 版本"""
        commands = [
            'php -v 2>/dev/null | head -1',
            'php-fpm -v 2>/dev/null | head -1',
            'php8.1 -v 2>/dev/null | head -1',
            'php8.0 -v 2>/dev/null | head -1',
            'php7.4 -v 2>/dev/null | head -1',
        ]
        for cmd in commands:
            stdout, _, _ = self.ssh.exec_command(server_id, cmd)
            if stdout and 'PHP' in stdout:
                return stdout.split()[1] if len(stdout.split()) > 1 else stdout
        return '未安装'

    def _get_mysql_version(self, server_id):
        """获取 MySQL 版本"""
        commands = [
            'mysql --version 2>/dev/null',
            'mariadb --version 2>/dev/null',
        ]
        for cmd in commands:
            stdout, _, _ = self.ssh.exec_command(server_id, cmd)
            if stdout:
                parts = stdout.split()
                for i, part in enumerate(parts):
                    if 'Ver' in part or 'ver' in part:
                        return parts[i + 1] if i + 1 < len(parts) else stdout
                return stdout
        return '未安装'

    def _get_open_ports(self, server_id):
        """获取开放端口"""
        stdout, _, _ = self.ssh.exec_command(
            server_id,
            "ss -tlnp 2>/dev/null | awk 'NR>1 {print $4}' | sed 's/.*://' | sort -un | head -50"
        )
        if not stdout:
            stdout, _, _ = self.ssh.exec_command(
                server_id,
                "netstat -tlnp 2>/dev/null | awk 'NR>2 {print $4}' | sed 's/.*://' | sort -un | head -50"
            )

        ports = []
        if stdout:
            for line in stdout.split('\n'):
                line = line.strip()
                if line and line.isdigit():
                    ports.append(line)
        return json.dumps(ports)

    def _get_processes(self, server_id):
        """获取进程列表"""
        stdout, _, _ = self.ssh.exec_command(
            server_id,
            "ps aux | head -30"
        )
        processes = []
        if stdout:
            for line in stdout.split('\n'):
                line = line.strip()
                if line and not line.startswith('COMMAND'):
                    processes.append(line)
        return json.dumps(processes)

    def _get_backdoor_users(self, server_id):
        """检测后门用户"""
        suspicious = []

        stdout, _, _ = self.ssh.exec_command(
            server_id,
            'awk -F: \'$3 == 0 && $1 != "root" {print $1}\' /etc/passwd'
        )
        if stdout:
            for user in stdout.split('\n'):
                user = user.strip()
                if user:
                    suspicious.append(f"UID=0用户: {user}")

        stdout, _, _ = self.ssh.exec_command(
            server_id,
            'awk -F: \'$2 == "" || $2 == "*" || $7 ~ /sh$/ {print $1"("$7")"}\' /etc/passwd'
        )
        if stdout:
            for line in stdout.split('\n'):
                line = line.strip()
                if line:
                    user = line.split('(')[0]
                    if user not in self.LEGIT_USERS:
                        suspicious.append(f"可疑用户: {line}")

        stdout, _, _ = self.ssh.exec_command(
            server_id,
            "lastlog 2>/dev/null | awk 'NR>1 && $4 != \"Never\" {print $1}'"
        )

        return json.dumps(list(set(suspicious)))

    def _get_priv_esc_files(self, server_id):
        """检测可提权文件（SUID/SGID）"""
        stdout, _, _ = self.ssh.exec_command(
            server_id,
            "find / -perm -4000 -type f 2>/dev/null"
        )

        suspicious = []
        if stdout:
            for line in stdout.split('\n'):
                line = line.strip()
                if line and line not in self.LEGIT_SUID_FILES:
                    suspicious.append(line)

        return json.dumps(suspicious)
