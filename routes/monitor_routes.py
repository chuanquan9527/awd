from flask import Blueprint, request, jsonify, current_app
from routes.auth_routes import login_required
from database.models import (
    AlertModel, MonitorConfigModel, ServerModel
)
from services.ssh_manager import SSHManager
from services.file_monitor import FileMonitor
from services.process_monitor import ProcessMonitor
import re

monitor_bp = Blueprint('monitor', __name__, url_prefix='/api')
ssh_manager = SSHManager()

# 全局 socketio 实例（从 app.py 导入）
_socketio = None

# 全局监控器实例（单例模式，避免每次请求创建新实例导致线程状态丢失）
_file_monitor = None
_process_monitor = None

def init_socketio(socketio):
    """初始化 socketio 实例"""
    global _socketio
    _socketio = socketio

# 延迟初始化监控器（需要 socketio）- 使用单例模式
def get_file_monitor():
    global _socketio, _file_monitor
    if _socketio is None:
        _socketio = current_app.extensions.get('socketio')
    if _file_monitor is None:
        _file_monitor = FileMonitor(ssh_manager, _socketio)
    return _file_monitor

def get_process_monitor():
    global _socketio, _process_monitor
    if _socketio is None:
        _socketio = current_app.extensions.get('socketio')
    if _process_monitor is None:
        _process_monitor = ProcessMonitor(ssh_manager, _socketio)
    return _process_monitor


# ==================== 文件监控 ====================

@monitor_bp.route('/servers/<int:server_id>/monitor/baseline', methods=['POST'])
@login_required
def build_baseline(server_id):
    """建立文件基线"""
    data = request.get_json() or {}
    dir_configs = data.get('dir_configs')  # 新格式：[{dir, whitelist}]
    directories = data.get('directories')  # 旧格式兼容
    whitelist = data.get('whitelist')  # 旧格式兼容
    
    # 处理参数兼容
    if not dir_configs:
        if directories:
            # 旧格式转换为新格式
            if isinstance(directories, list):
                dir_configs = [{'dir': d, 'whitelist': whitelist or ''} for d in directories]
            else:
                dir_configs = [{'dir': directories, 'whitelist': whitelist or ''}]
    
    try:
        monitor = get_file_monitor()
        result = monitor.build_baseline(server_id, dir_configs)
        return jsonify({'success': True, 'message': result['message'], 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'建立基线失败: {str(e)}'}), 500


@monitor_bp.route('/servers/<int:server_id>/monitor/start', methods=['POST'])
@login_required
def start_monitor(server_id):
    """启动监控（文件+进程+流量）"""
    data = request.get_json() or {}
    monitor_type = data.get('type', 'all')
    interval = data.get('interval', 5)
    kill_on_detect = data.get('kill_on_detect', False)
    dir_configs = data.get('dir_configs')  # 新格式：[{dir, whitelist}]
    directories = data.get('directories')  # 旧格式兼容
    whitelist = data.get('whitelist')  # 旧格式兼容

    # 处理参数兼容
    if not dir_configs and monitor_type in ('all', 'file'):
        if directories:
            if isinstance(directories, list):
                dir_configs = [{'dir': d, 'whitelist': whitelist or ''} for d in directories]
            else:
                dir_configs = [{'dir': directories, 'whitelist': whitelist or ''}]

    results = []
    try:
        if monitor_type in ('all', 'file'):
            fm = get_file_monitor()
            results.append(fm.start_monitoring(server_id, interval, dir_configs))

        if monitor_type in ('all', 'process'):
            pm = get_process_monitor()
            results.append(pm.start_monitoring(server_id, interval, kill_on_detect))

        return jsonify({'success': True, 'message': '监控已启动', 'data': results})
    except Exception as e:
        return jsonify({'success': False, 'message': f'启动监控失败: {str(e)}'}), 500


@monitor_bp.route('/servers/<int:server_id>/monitor/stop', methods=['POST'])
@login_required
def stop_monitor(server_id):
    """停止监控"""
    data = request.get_json() or {}
    monitor_type = data.get('type', 'all')

    results = []
    try:
        if monitor_type in ('all', 'file'):
            fm = get_file_monitor()
            # 强制停止：先检查线程状态
            if server_id in fm._threads and fm._threads[server_id].is_alive():
                print(f'[监控] 强制停止服务器 {server_id} 的文件监控线程')
            results.append(fm.stop_monitoring(server_id))

        if monitor_type in ('all', 'process'):
            pm = get_process_monitor()
            if server_id in pm._threads and pm._threads[server_id].is_alive():
                print(f'[监控] 强制停止服务器 {server_id} 的进程监控线程')
            results.append(pm.stop_monitoring(server_id))

        success = all(r.get('success') for r in results)
        return jsonify({
            'success': success,
            'message': '监控已停止' if success else '部分监控停止失败',
            'results': results
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'停止监控失败: {str(e)}'}), 500


@monitor_bp.route('/servers/<int:server_id>/monitor/status', methods=['GET'])
@login_required
def get_monitor_status(server_id):
    """获取监控状态"""
    config = MonitorConfigModel.get_by_server(server_id)
    
    # 检查是否有基线
    from database.db import get_db
    with get_db() as conn:
        baseline_count = conn.execute(
            'SELECT COUNT(*) FROM file_baselines WHERE server_id = ?',
            [server_id]
        ).fetchone()[0]
    
    if config:
        return jsonify({
            'success': True,
            'data': {
                'file_monitor_enabled': bool(config['file_monitor_enabled']),
                'process_monitor_enabled': bool(config['process_monitor_enabled']),
                'monitor_interval': config['monitor_interval'],
                'kill_on_detect': bool(config['kill_on_detect']),
                'watched_dirs': config['watched_dirs'],
                'whitelist': config['whitelist'] or '',  # 返回白名单
                'has_baseline': baseline_count > 0
            }
        })
    return jsonify({'success': True, 'data': {
        'file_monitor_enabled': False,
        'process_monitor_enabled': False,
        'monitor_interval': 5,
        'kill_on_detect': False,
        'watched_dirs': '[]',
        'whitelist': '',  # 默认空白名单
        'has_baseline': baseline_count > 0
    }})


# ==================== 进程监控 ====================

@monitor_bp.route('/servers/<int:server_id>/processes', methods=['GET'])
@login_required
def get_processes(server_id):
    """获取进程列表"""
    try:
        pm = get_process_monitor()
        processes = pm.get_process_list(server_id)
        return jsonify({'success': True, 'data': processes})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取进程列表失败: {str(e)}'}), 500


@monitor_bp.route('/servers/<int:server_id>/processes/<int:pid>/kill', methods=['POST'])
@login_required
def kill_process(server_id, pid):
    """杀死进程"""
    try:
        pm = get_process_monitor()
        success = pm.kill_process(server_id, str(pid))
        if success:
            return jsonify({'success': True, 'message': f'进程 {pid} 已终止'})
        return jsonify({'success': False, 'message': f'终止进程 {pid} 失败'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'}), 500


# ==================== 告警 ====================

@monitor_bp.route('/alerts', methods=['GET'])
@login_required
def get_alerts():
    """获取告警列表"""
    limit = request.args.get('limit', 100, type=int)
    unread_only = request.args.get('unread', 'false').lower() == 'true'
    alerts = AlertModel.get_all(limit, unread_only)
    return jsonify({
        'success': True,
        'data': [dict(row) for row in alerts],
        'unread_count': AlertModel.get_unread_count()
    })


@monitor_bp.route('/alerts/<int:alert_id>/read', methods=['PUT'])
@login_required
def mark_alert_read(alert_id):
    """标记告警已读"""
    AlertModel.mark_read(alert_id)
    return jsonify({'success': True})


@monitor_bp.route('/alerts/read-all', methods=['PUT'])
@login_required
def mark_all_alerts_read():
    """标记所有告警已读"""
    from database.db import get_db
    with get_db() as conn:
        conn.execute('UPDATE alerts SET is_read = 1 WHERE is_read = 0')
        conn.commit()
    return jsonify({'success': True, 'message': '所有告警已标记为已读'})


@monitor_bp.route('/alerts/<int:alert_id>', methods=['DELETE'])
@login_required
def delete_alert(alert_id):
    """删除单条告警"""
    from database.db import get_db
    try:
        with get_db() as conn:
            result = conn.execute('DELETE FROM alerts WHERE id = ?', [alert_id])
            conn.commit()
            if result.rowcount > 0:
                return jsonify({'success': True, 'message': '告警已删除'})
            return jsonify({'success': False, 'message': '告警不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


@monitor_bp.route('/alerts/batch', methods=['DELETE'])
@login_required
def delete_alerts_batch():
    """批量删除告警"""
    from database.db import get_db
    data = request.get_json() or {}
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'success': False, 'message': '请选择要删除的告警'}), 400
    
    try:
        with get_db() as conn:
            # 使用参数化查询防止SQL注入
            placeholders = ','.join(['?' for _ in ids])
            result = conn.execute(f'DELETE FROM alerts WHERE id IN ({placeholders})', ids)
            conn.commit()
            return jsonify({'success': True, 'message': f'已删除 {result.rowcount} 条告警'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


@monitor_bp.route('/alerts/all', methods=['DELETE'])
@login_required
def delete_all_alerts():
    """删除所有告警"""
    from database.db import get_db
    try:
        with get_db() as conn:
            result = conn.execute('DELETE FROM alerts')
            conn.commit()
            return jsonify({'success': True, 'message': f'已删除 {result.rowcount} 条告警'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


