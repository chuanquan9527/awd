import re
import json
import threading
import time
from datetime import datetime
from database.models import ServerModel, AlertModel, TrafficRuleModel, TrafficAlertModel, MonitorConfigModel
from config import MONITOR_DEFAULT_INTERVAL, MONITOR_MIN_INTERVAL, TRAFFIC_LOG_PATHS


# Apache/Nginx 日志解析正则
LOG_PATTERNS = [
    # Apache Combined Log Format
    re.compile(
        r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>\S+) (?P<uri>\S+) \S+" (?P<status>\d+)'
    ),
    # Nginx Default Format
    re.compile(
        r'^(?P<ip>\S+) - (?P<user>\S+) \[(?P<time>[^\]]+)\] "(?P<method>\S+) (?P<uri>\S+) \S+" (?P<status>\d+)'
    ),
    # 简单格式
    re.compile(
        r'^(?P<ip>\S+) .* "(?P<method>\S+) (?P<uri>\S+)'
    ),
]


class TrafficMonitor:
    """流量监控 - 实时日志跟踪 + 正则规则匹配"""

    def __init__(self, ssh_manager, socketio):
        self.ssh = ssh_manager
        self.socketio = socketio
        self._threads = {}       # {server_id: threading.Thread}
        self._events = {}        # {server_id: threading.Event}

    def start_monitoring(self, server_id, interval=MONITOR_DEFAULT_INTERVAL):
        """启动流量监控（通过 SSH tail -F 实时跟踪日志）"""
        if server_id in self._threads and self._threads[server_id].is_alive():
            return {'success': False, 'message': '流量监控已在运行中'}

        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        MonitorConfigModel.create_or_update(
            server_id,
            traffic_monitor_enabled=1
        )

        self._events[server_id] = threading.Event()

        thread = threading.Thread(
            target=self._tail_log,
            args=(server_id, server),
            daemon=True
        )
        self._threads[server_id] = thread
        thread.start()

        return {'success': True, 'message': '流量监控已启动'}

    def stop_monitoring(self, server_id):
        """停止流量监控"""
        # 设置停止事件
        if server_id in self._events:
            self._events[server_id].set()
        
        # 等待线程结束（最多等待5秒）
        if server_id in self._threads:
            thread = self._threads[server_id]
            if thread.is_alive():
                thread.join(timeout=5)
            # 清理线程引用
            if not thread.is_alive():
                del self._threads[server_id]
        
        # 清理事件引用
        if server_id in self._events:
            del self._events[server_id]
        
        # 更新数据库配置
        MonitorConfigModel.create_or_update(
            server_id,
            traffic_monitor_enabled=0
        )

        return {'success': True, 'message': '流量监控已停止'}

    def _tail_log(self, server_id, server):
        """通过 SSH tail -F 实时跟踪日志"""
        # 查找日志文件路径
        log_path = self._find_log_path(server_id)
        if not log_path:
            print(f'[流量监控] 服务器 {server_id} 未找到访问日志文件')
            return

        # 使用 tail -F 持续跟踪
        cmd = f"tail -F {log_path} 2>/dev/null"

        try:
            client = self.ssh.get_connection(server_id)
            stdin, stdout, stderr = client.exec_command(cmd, timeout=None)

            # 逐行读取
            stop_event = self._events.get(server_id, threading.Event())
            for line in stdout:
                if stop_event.is_set():
                    break
                line = line.strip()
                if line:
                    self._process_log_line(server_id, server, line)
        except Exception as e:
            if not self._events.get(server_id, threading.Event()).is_set():
                print(f'[流量监控] 服务器 {server_id} 连接中断: {e}')
                # 自动重连
                time.sleep(5)
                if not self._events.get(server_id, threading.Event()).is_set():
                    self._tail_log(server_id, server)

    def _find_log_path(self, server_id):
        """查找 Web 服务器日志文件路径"""
        # 按优先级检查
        for path in [
            '/var/log/apache2/access.log',
            '/var/log/httpd/access_log',
            '/var/log/nginx/access.log',
            '/usr/local/nginx/logs/access.log',
        ]:
            stdout, _, code = self.ssh.exec_command(
                server_id,
                f'test -f {path} && echo "exists" || echo "not_found"',
                timeout=10
            )
            if 'exists' in stdout:
                return path
        return None

    def _process_log_line(self, server_id, server, log_line):
        """处理单条日志"""
        # 解析日志基本信息
        parsed = self._parse_log_line(log_line)
        if not parsed:
            return

        # 获取启用的规则
        rules = TrafficRuleModel.get_enabled_rules(server_id)

        # 对每条规则进行匹配
        for rule in rules:
            try:
                pattern = re.compile(rule['pattern'])
                match = pattern.search(log_line)
                if match:
                    matched_content = match.group(0)

                    # 记录流量告警
                    TrafficAlertModel.create(
                        server_id=server_id,
                        rule_id=rule['id'],
                        matched_pattern=rule['pattern'],
                        source_ip=parsed.get('ip', ''),
                        request_method=parsed.get('method', ''),
                        request_uri=parsed.get('uri', ''),
                        request_body='',
                        matched_content=matched_content[:2000]
                    )

                    # 发送告警
                    self._emit_alert(server_id, server['name'], rule, parsed, matched_content)
            except re.error:
                continue

    def _parse_log_line(self, log_line):
        """解析日志行"""
        for pattern in LOG_PATTERNS:
            match = pattern.match(log_line)
            if match:
                return match.groupdict()
        return None

    def _emit_alert(self, server_id, server_name, rule, parsed, matched_content):
        """发送告警"""
        AlertModel.create(
            server_id=server_id,
            alert_type='traffic_rule',
            severity=rule['severity'],
            message=f'[{rule["rule_name"]}] 来源IP: {parsed.get("ip", "")} | {parsed.get("method", "")} {parsed.get("uri", "")}',
            details=json.dumps({
                'rule_name': rule['rule_name'],
                'rule_id': rule['id'],
                'source_ip': parsed.get('ip', ''),
                'method': parsed.get('method', ''),
                'uri': parsed.get('uri', ''),
                'matched_content': matched_content[:500]
            })
        )

        # WebSocket 推送（广播给所有客户端）
        if self.socketio:
            self.socketio.emit('alert', {
                'type': 'traffic_rule',
                'severity': rule['severity'],
                'server_id': server_id,
                'server_name': server_name,
                'message': f'[{rule["rule_name"]}] {parsed.get("ip", "")} -> {parsed.get("method", "")} {parsed.get("uri", "")}',
                'details': {
                    'rule_name': rule['rule_name'],
                    'source_ip': parsed.get('ip', ''),
                    'method': parsed.get('method', ''),
                    'uri': parsed.get('uri', ''),
                    'matched_content': matched_content[:200]
                },
                'timestamp': datetime.now().isoformat()
            })
