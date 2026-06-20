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
        self._dir_configs = {}   # {server_id: [{dir, whitelist_patterns}]}

    def _parse_whitelist(self, whitelist_str):
        """解析白名单字符串为正则表达式列表"""
        if not whitelist_str:
            return []
        
        patterns = []
        for line in whitelist_str.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                pattern = re.compile(line)
                patterns.append(pattern)
            except re.error as e:
                print(f'[文件监控] 白名单正则表达式错误: {line}, 错误: {e}')
        return patterns

    def _is_whitelisted(self, file_path, patterns):
        """检查文件路径是否匹配白名单"""
        for pattern in patterns:
            if pattern.search(file_path):
                return True
        return False

    def _get_whitelist_for_file(self, file_path, dir_configs):
        """根据文件路径获取对应的白名单"""
        for config in dir_configs:
            dir_path = config.get('dir', '')
            patterns = config.get('whitelist_patterns', [])
            # 检查文件是否属于该目录
            if file_path.startswith(dir_path):
                return patterns
        return []

    def build_baseline(self, server_id, dir_configs=None):
        """建立文件基线
        
        Args:
            server_id: 服务器ID
            dir_configs: 目录配置列表，格式为 [{dir: '/path', whitelist: 'regex patterns'}]
        """
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise Exception('服务器不存在')

        # 处理目录配置
        if not dir_configs:
            dir_configs = [{'dir': server['web_root'], 'whitelist': ''}]
        
        # 确保格式正确
        if isinstance(dir_configs, list) and len(dir_configs) > 0:
            if isinstance(dir_configs[0], str):
                # 旧格式转换
                dir_configs = [{'dir': d, 'whitelist': ''} for d in dir_configs]
        
        # 解析每个目录的白名单
        processed_configs = []
        for config in dir_configs:
            dir_path = config.get('dir', '')
            whitelist_str = config.get('whitelist', '')
            patterns = self._parse_whitelist(whitelist_str)
            processed_configs.append({
                'dir': dir_path,
                'whitelist': whitelist_str,
                'whitelist_patterns': patterns
            })
        
        # 保存到内存
        self._dir_configs[server_id] = processed_configs
        
        # 获取所有目录
        directories = [c['dir'] for c in processed_configs if c['dir']]

        # 在服务器上计算所有文件的 MD5
        # 使用 -L 参数跟随符号链接，解决 /var/www/html -> /app 等符号链接问题
        find_cmd = ' '.join([f"'{d}'" for d in directories])
        cmd = f"find -L {find_cmd} -type f -exec md5sum {{}} \\; 2>/dev/null"
        stdout, stderr, code = self.ssh.exec_command(server_id, cmd, timeout=120)

        if code != 0 and not stdout:
            raise Exception(f'获取文件列表失败: {stderr}')

        # 解析 md5sum 输出: "hash  filepath"
        file_hashes = {}
        whitelisted_count = 0
        for line in stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                md5_hash, file_path = parts
                # 根据文件所在目录获取对应的白名单
                patterns = self._get_whitelist_for_file(file_path, processed_configs)
                if patterns and self._is_whitelisted(file_path, patterns):
                    whitelisted_count += 1
                    continue
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

        # 更新监控配置（使用新格式）
        # 保存为 [{dir, whitelist}] 格式
        save_configs = [{'dir': c['dir'], 'whitelist': c['whitelist']} for c in processed_configs]
        MonitorConfigModel.create_or_update(
            server_id,
            watched_dirs=json.dumps(save_configs)
        )

        return {
            'success': True,
            'message': f'基线建立完成，共 {len(file_hashes)} 个文件（白名单过滤 {whitelisted_count} 个）',
            'file_count': len(file_hashes),
            'whitelisted_count': whitelisted_count
        }

    def start_monitoring(self, server_id, interval=MONITOR_DEFAULT_INTERVAL, dir_configs=None):
        """启动文件监控
        
        Args:
            server_id: 服务器ID
            interval: 监控间隔
            dir_configs: 目录配置列表，格式为 [{dir: '/path', whitelist: 'regex patterns'}]
        """
        if server_id in self._threads and self._threads[server_id].is_alive():
            return {'success': False, 'message': '监控已在运行中'}

        interval = max(MONITOR_MIN_INTERVAL, min(interval, 300))

        # 获取服务器信息，用于默认目录
        server = ServerModel.get_by_id(server_id)
        
        # 处理目录配置
        if not dir_configs:
            dir_configs = [{'dir': server['web_root'] if server else '/var/www/html', 'whitelist': ''}]
        
        # 确保格式正确
        if isinstance(dir_configs, list) and len(dir_configs) > 0:
            if isinstance(dir_configs[0], str):
                # 旧格式转换
                dir_configs = [{'dir': d, 'whitelist': ''} for d in dir_configs]
        
        # 解析每个目录的白名单
        processed_configs = []
        for config in dir_configs:
            dir_path = config.get('dir', '')
            whitelist_str = config.get('whitelist', '')
            patterns = self._parse_whitelist(whitelist_str)
            processed_configs.append({
                'dir': dir_path,
                'whitelist': whitelist_str,
                'whitelist_patterns': patterns
            })
        
        # 保存到内存
        self._dir_configs[server_id] = processed_configs
        
        # 更新监控配置
        save_configs = [{'dir': c['dir'], 'whitelist': c['whitelist']} for c in processed_configs]
        MonitorConfigModel.create_or_update(
            server_id,
            file_monitor_enabled=1,
            monitor_interval=interval,
            watched_dirs=json.dumps(save_configs)
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
        
        # 清理目录配置
        if server_id in self._dir_configs:
            del self._dir_configs[server_id]
        
        # 更新数据库配置
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

        # 获取目录配置（优先使用内存中的，否则从配置解析）
        dir_configs = self._dir_configs.get(server_id)
        if dir_configs is None:
            config = MonitorConfigModel.get_by_server(server_id)
            if config and config['watched_dirs']:
                try:
                    saved_configs = json.loads(config['watched_dirs'])
                    # 解析配置
                    dir_configs = []
                    if saved_configs and len(saved_configs) > 0:
                        if isinstance(saved_configs[0], str):
                            # 旧格式转换
                            for d in saved_configs:
                                dir_configs.append({
                                    'dir': d,
                                    'whitelist': '',
                                    'whitelist_patterns': []
                                })
                        else:
                            # 新格式
                            for c in saved_configs:
                                patterns = self._parse_whitelist(c.get('whitelist', ''))
                                dir_configs.append({
                                    'dir': c.get('dir', ''),
                                    'whitelist': c.get('whitelist', ''),
                                    'whitelist_patterns': patterns
                                })
                except Exception as e:
                    print(f'[文件监控] 解析配置失败: {e}')
                    dir_configs = [{'dir': server['web_root'], 'whitelist': '', 'whitelist_patterns': []}]
            else:
                dir_configs = [{'dir': server['web_root'], 'whitelist': '', 'whitelist_patterns': []}]
            self._dir_configs[server_id] = dir_configs

        # 获取所有目录
        directories = [c['dir'] for c in dir_configs if c['dir']]
        if not directories:
            directories = [server['web_root']]

        # 获取当前文件 MD5
        # 使用 -L 参数跟随符号链接
        find_cmd = ' '.join([f"'{d}'" for d in directories])
        cmd = f"find -L {find_cmd} -type f -exec md5sum {{}} \\; 2>/dev/null"
        stdout, _, _ = self.ssh.exec_command(server_id, cmd, timeout=120)

        current_hashes = {}
        for line in stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                file_path = parts[1]
                # 根据文件所在目录获取对应的白名单
                patterns = self._get_whitelist_for_file(file_path, dir_configs)
                if patterns and self._is_whitelisted(file_path, patterns):
                    continue
                current_hashes[file_path] = parts[0]

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

        # 检测删除文件（排除白名单中的文件）
        deleted_files = baseline_paths - current_paths
        for f in deleted_files:
            # 检查是否现在属于白名单（可能是白名单后来被更新）
            patterns = self._get_whitelist_for_file(f, dir_configs)
            if patterns and self._is_whitelisted(f, patterns):
                continue
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
        """发送告警（防止重复）"""
        # 检查是否已存在相同的告警（同一服务器、同一文件路径、同一告警类型）
        # 使用文件路径作为唯一标识，避免短时间内重复告警
        file_path = alert.get('path', '')
        alert_type = alert.get('type', '')
        
        from database.db import get_db
        with get_db() as conn:
            # 检查最近5分钟内是否已有相同告警
            existing = conn.execute(
                '''SELECT id FROM alerts 
                   WHERE server_id = ? 
                   AND alert_type = 'file_change'
                   AND message LIKE ?
                   AND created_at > datetime('now', '-5 minutes')
                   LIMIT 1''',
                [server_id, f'%{file_path}%']
            ).fetchone()
            
            if existing:
                # 已存在相同告警，跳过
                return
        
        # 写入数据库
        AlertModel.create(
            server_id=server_id,
            alert_type='file_change',
            severity=alert['severity'],
            message=alert['message'],
            details=json.dumps(alert)
        )

        # WebSocket 推送（广播给所有客户端）
        if self.socketio:
            self.socketio.emit('alert', {
                'type': 'file_change',
                'severity': alert['severity'],
                'server_id': server_id,
                'server_name': server_name,
                'message': alert['message'],
                'details': alert,
                'timestamp': datetime.now().isoformat()
            })