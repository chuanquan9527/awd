import re
import json
import threading
import time
from datetime import datetime
from database.models import ServerModel, AlertModel, MonitorConfigModel
from config import MONITOR_DEFAULT_INTERVAL, MONITOR_MIN_INTERVAL


class FileMonitor:
    """文件完整性监控 - MD5 基线比对"""

    def __init__(self, ssh_manager, socketio):
        self.ssh = ssh_manager
        self.socketio = socketio
        self._threads = {}       # {server_id: threading.Thread}
        self._events = {}        # {server_id: threading.Event}

    def build_baseline(self, server_id, directories=None):
        """建立文件基线"""
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        if not directories:
            directories = [server['web_root']]

        # 在服务器上计算所有文件的 MD5
        find_cmd = ' '.join([f"'{d}'" for d in directories])
        cmd = f"find {find_cmd} -type f -exec md5sum {{}} \\; 2>/dev/null"
        stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=120)

        if code != 0 and not stdout:
            raise Exception(f'获取文件列表失败: {stderr}')

        # 解析 md5sum 输出: "hash  filepath"
        file_hashes = {}
        for line in stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                md5_hash, file_path = parts
                file_hashes[file_path] = md5_hash

        # 存入数据库
        from database.db import get_db
        with get_db() as conn:
            # 删除旧基线
            conn.execute('DELETE FROM file_baselines WHERE server_id = ?', [server_id])
            # 插入新基线
            for file_path, md5_hash in file_hashes.items():
                conn.execute(
                    'INSERT OR REPLACE INTO file_baselines (server_id, file_path, md5_hash) VALUES (?, ?, ?)',
                    [server_id, file_path, md5_hash]
                )
            conn.commit()

        # 更新监控配置
        MonitorConfigModel.create_or_update(
            server_id,
            watched_dirs=json.dumps(directories)
        )

        return {
            'success': True,
            'message': f'基线建立完成，共 {len(file_hashes)} 个文件',
            'file_count': len(file_hashes)
        }

    def start_monitoring(self, server_id, interval=MONITOR_DEFAULT_INTERVAL):
        """启动文件监控"""
        if server_id in self._threads and self._threads[server_id].is_alive():
            return {'success': False, 'message': '监控已在运行中'}

        interval = max(MONITOR_MIN_INTERVAL, min(interval, 300))

        # 更新监控配置
        MonitorConfigModel.create_or_update(
            server_id,
            file_monitor_enabled=1,
            monitor_interval=interval
        )

        # 创建停止事件
        self._events[server_id] = threading.Event()

        # 启动监控线程
        thread = threading.Thread(
            target=self._monitor_loop,
            args=(server_id, interval),
            daemon=True
        )
        self._threads[server_id] = thread
        thread.start()

        return {'success': True, 'message': f'文件监控已启动，间隔 {interval} 秒'}

    def stop_monitoring(self, server_id):
        """停止文件监控"""
        if server_id in self._events:
            self._events[server_id].set()

        MonitorConfigModel.create_or_update(
            server_id,
            file_monitor_enabled=0
        )

        return {'success': True, 'message': '文件监控已停止'}

    def _monitor_loop(self, server_id, interval):
        """监控循环"""
        while not self._events.get(server_id, threading.Event()).is_set():
            try:
                self.check_integrity(server_id)
            except Exception as e:
                print(f'[文件监控] 服务器 {server_id} 检查异常: {e}')
            # 等待间隔或停止信号
            self._events[server_id].wait(interval)

    def check_integrity(self, server_id):
        """执行一次完整性检查"""
        server = ServerModel.get_by_id(server_id)
        if not server:
            return []

        config = MonitorConfigModel.get_by_server(server_id)
        directories = json.loads(config['watched_dirs']) if config and config['watched_dirs'] else [server['web_root']]

        # 获取当前文件 MD5
        find_cmd = ' '.join([f"'{d}'" for d in directories])
        cmd = f"find {find_cmd} -type f -exec md5sum {{}} \\; 2>/dev/null"
        stdout, _, _ = self.ssh.exec_command(server_id, cmd, timeout=120)

        current_hashes = {}
        for line in stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                current_hashes[parts[1]] = parts[0]

        # 获取基线
        from database.db import get_db
        with get_db() as conn:
            rows = conn.execute(
                'SELECT file_path, md5_hash FROM file_baselines WHERE server_id = ?',
                [server_id]
            ).fetchall()
            baseline = {row['file_path']: row['md5_hash'] for row in rows}

        alerts = []

        # 检测新增文件
        baseline_paths = set(baseline.keys())
        current_paths = set(current_hashes.keys())

        new_files = current_paths - baseline_paths
        for f in new_files:
            alert = {
                'type': 'new_file',
                'path': f,
                'severity': 'critical',
                'message': f'检测到新增文件: {f}'
            }
            alerts.append(alert)
            self._emit_alert(server_id, server['name'], alert)

        # 检测修改文件
        common_files = baseline_paths & current_paths
        for f in common_files:
            if baseline[f] != current_hashes[f]:
                alert = {
                    'type': 'modified_file',
                    'path': f,
                    'old_hash': baseline[f],
                    'new_hash': current_hashes[f],
                    'severity': 'critical',
                    'message': f'文件被篡改: {f}'
                }
                alerts.append(alert)
                self._emit_alert(server_id, server['name'], alert)

        # 检测删除文件
        deleted_files = baseline_paths - current_paths
        for f in deleted_files:
            alert = {
                'type': 'deleted_file',
                'path': f,
                'severity': 'warning',
                'message': f'文件被删除: {f}'
            }
            alerts.append(alert)
            self._emit_alert(server_id, server['name'], alert)

        return alerts

    def _emit_alert(self, server_id, server_name, alert):
        """发送告警"""
        # 写入数据库
        AlertModel.create(
            server_id=server_id,
            alert_type='file_change',
            severity=alert['severity'],
            message=alert['message'],
            details=json.dumps(alert)
        )

        # WebSocket 推送
        self.socketio.emit('alert', {
            'type': 'file_change',
            'severity': alert['severity'],
            'server_id': server_id,
            'server_name': server_name,
            'message': alert['message'],
            'details': alert,
            'timestamp': datetime.now().isoformat()
        }, broadcast=True)
