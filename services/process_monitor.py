import re
import json
import threading
import time
from datetime import datetime
from database.models import ServerModel, AlertModel, MonitorConfigModel
from config import MONITOR_DEFAULT_INTERVAL, MONITOR_MIN_INTERVAL, PROCESS_MONITOR_SUSPICIOUS_PATTERNS


class ProcessMonitor:
    """进程监控 - 检测异常进程"""

    def __init__(self, ssh_manager, socketio):
        self.ssh = ssh_manager
        self.socketio = socketio
        self._threads = {}       # {server_id: threading.Thread}
        self._events = {}        # {server_id: threading.Event}
        self._patterns = [re.compile(p) for p in PROCESS_MONITOR_SUSPICIOUS_PATTERNS]

    def start_monitoring(self, server_id, interval=MONITOR_DEFAULT_INTERVAL, kill_on_detect=False):
        """启动进程监控"""
        if server_id in self._threads and self._threads[server_id].is_alive():
            return {'success': False, 'message': '进程监控已在运行中'}

        interval = max(MONITOR_MIN_INTERVAL, min(interval, 300))

        MonitorConfigModel.create_or_update(
            server_id,
            process_monitor_enabled=1,
            monitor_interval=interval,
            kill_on_detect=1 if kill_on_detect else 0
        )

        self._events[server_id] = threading.Event()

        thread = threading.Thread(
            target=self._monitor_loop,
            args=(server_id, interval, kill_on_detect),
            daemon=True
        )
        self._threads[server_id] = thread
        thread.start()

        return {'success': True, 'message': f'进程监控已启动，间隔 {interval} 秒'}

    def stop_monitoring(self, server_id):
        """停止进程监控"""
        if server_id in self._events:
            self._events[server_id].set()

        MonitorConfigModel.create_or_update(
            server_id,
            process_monitor_enabled=0
        )

        return {'success': True, 'message': '进程监控已停止'}

    def _monitor_loop(self, server_id, interval, kill_on_detect):
        """监控循环"""
        while not self._events.get(server_id, threading.Event()).is_set():
            try:
                self.check_processes(server_id, kill_on_detect)
            except Exception as e:
                print(f'[进程监控] 服务器 {server_id} 检查异常: {e}')
            self._events[server_id].wait(interval)

    def check_processes(self, server_id, kill_on_detect=False):
        """检查进程列表，返回异常进程"""
        server = ServerModel.get_by_id(server_id)
        if not server:
            return []

        stdout, _, _ = self.ssh.exec_command(server_id, 'ps aux', timeout=30)

        suspicious = []
        for line in stdout.split('\n'):
            line = line.strip()
            if not line or line.startswith('COMMAND') or line.startswith('USER'):
                continue

            # 检测可疑模式
            for pattern in self._patterns:
                if pattern.search(line):
                    # 提取 PID
                    parts = line.split(None, 2)
                    pid = parts[1] if len(parts) > 1 else 'unknown'
                    cmd = parts[2] if len(parts) > 2 else line

                    alert = {
                        'type': 'suspicious_process',
                        'pid': pid,
                        'command': cmd,
                        'pattern': pattern.pattern,
                        'severity': 'critical',
                        'message': f'检测到可疑进程 PID={pid}: {cmd[:100]}'
                    }
                    suspicious.append(alert)

                    # 自动杀进程
                    if kill_on_detect:
                        self.kill_process(server_id, pid)
                        alert['killed'] = True
                        alert['message'] += ' (已自动终止)'

                    # 发送告警
                    self._emit_alert(server_id, server['name'], alert)
                    break  # 每个进程只匹配一次

        return suspicious

    def kill_process(self, server_id, pid):
        """杀死指定进程"""
        stdout, stderr, code = self.ssh.exec_command(
            server_id, f'kill -9 {pid} 2>/dev/null', timeout=10
        )
        return code == 0

    def get_process_list(self, server_id):
        """获取进程列表（用于前端展示）"""
        server = ServerModel.get_by_id(server_id)
        if not server:
            return []

        stdout, _, _ = self.ssh.exec_command(server_id, 'ps aux', timeout=30)

        processes = []
        for line in stdout.split('\n'):
            line = line.strip()
            if not line or line.startswith('COMMAND') or line.startswith('USER'):
                continue

            parts = line.split(None, 10)
            if len(parts) < 11:
                continue

            proc = {
                'user': parts[0],
                'pid': parts[1],
                'cpu': parts[2],
                'mem': parts[3],
                'vsz': parts[4],
                'rss': parts[5],
                'stat': parts[7] if len(parts) > 7 else '',
                'command': parts[10] if len(parts) > 10 else parts[-1],
                'suspicious': False
            }

            # 标记可疑进程
            for pattern in self._patterns:
                if pattern.search(line):
                    proc['suspicious'] = True
                    break

            processes.append(proc)

        return processes

    def _emit_alert(self, server_id, server_name, alert):
        """发送告警"""
        AlertModel.create(
            server_id=server_id,
            alert_type='process_anomaly',
            severity=alert['severity'],
            message=alert['message'],
            details=json.dumps(alert)
        )

        self.socketio.emit('alert', {
            'type': 'process_anomaly',
            'severity': alert['severity'],
            'server_id': server_id,
            'server_name': server_name,
            'message': alert['message'],
            'details': alert,
            'timestamp': datetime.now().isoformat()
        }, broadcast=True)
