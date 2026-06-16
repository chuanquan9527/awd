from flask import Blueprint, request, jsonify, current_app
from routes.auth_routes import login_required
from database.models import (
    TrafficRuleModel, TrafficAlertModel, AlertModel, MonitorConfigModel, ServerModel
)
from services.ssh_manager import SSHManager
from services.file_monitor import FileMonitor
from services.process_monitor import ProcessMonitor
from services.traffic_monitor import TrafficMonitor
import re

monitor_bp = Blueprint('monitor', __name__, url_prefix='/api')
ssh_manager = SSHManager()

# 延迟初始化监控器（需要 socketio）
def get_file_monitor():
    return FileMonitor(ssh_manager, current_app.extensions.get('socketio'))

def get_process_monitor():
    return ProcessMonitor(ssh_manager, current_app.extensions.get('socketio'))

def get_traffic_monitor():
    return TrafficMonitor(ssh_manager, current_app.extensions.get('socketio'))


# ==================== 文件监控 ====================

@monitor_bp.route('/servers/<int:server_id>/monitor/baseline', methods=['POST'])
@login_required
def build_baseline(server_id):
    """建立文件基线"""
    data = request.get_json() or {}
    directories = data.get('directories')
    try:
        monitor = get_file_monitor()
        result = monitor.build_baseline(server_id, directories)
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

    results = []
    try:
        if monitor_type in ('all', 'file'):
            fm = get_file_monitor()
            results.append(fm.start_monitoring(server_id, interval))

        if monitor_type in ('all', 'process'):
            pm = get_process_monitor()
            results.append(pm.start_monitoring(server_id, interval, kill_on_detect))

        if monitor_type in ('all', 'traffic'):
            tm = get_traffic_monitor()
            results.append(tm.start_monitoring(server_id))

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
            results.append(fm.stop_monitoring(server_id))

        if monitor_type in ('all', 'process'):
            pm = get_process_monitor()
            results.append(pm.stop_monitoring(server_id))

        if monitor_type in ('all', 'traffic'):
            tm = get_traffic_monitor()
            results.append(tm.stop_monitoring(server_id))

        return jsonify({'success': True, 'message': '监控已停止', 'data': results})
    except Exception as e:
        return jsonify({'success': False, 'message': f'停止监控失败: {str(e)}'}), 500


@monitor_bp.route('/servers/<int:server_id>/monitor/status', methods=['GET'])
@login_required
def get_monitor_status(server_id):
    """获取监控状态"""
    config = MonitorConfigModel.get_by_server(server_id)
    if config:
        return jsonify({
            'success': True,
            'data': {
                'file_monitor_enabled': bool(config['file_monitor_enabled']),
                'process_monitor_enabled': bool(config['process_monitor_enabled']),
                'traffic_monitor_enabled': bool(config['traffic_monitor_enabled']),
                'monitor_interval': config['monitor_interval'],
                'kill_on_detect': bool(config['kill_on_detect']),
                'watched_dirs': config['watched_dirs']
            }
        })
    return jsonify({'success': True, 'data': {
        'file_monitor_enabled': False,
        'process_monitor_enabled': False,
        'traffic_monitor_enabled': False,
        'monitor_interval': 5,
        'kill_on_detect': False,
        'watched_dirs': '[]'
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


# ==================== 流量监控规则 API ====================

@monitor_bp.route('/traffic/rules', methods=['GET'])
@login_required
def get_traffic_rules():
    """获取流量监控规则列表"""
    server_id = request.args.get('server_id', type=int)
    rules = TrafficRuleModel.get_all(server_id)
    return jsonify({
        'success': True,
        'data': [dict(row) for row in rules]
    })


@monitor_bp.route('/traffic/rules', methods=['POST'])
@login_required
def add_traffic_rule():
    """新增流量监控规则"""
    data = request.get_json()

    if not data.get('rule_name') or not data.get('pattern'):
        return jsonify({'success': False, 'message': '规则名称和正则表达式不能为空'}), 400

    try:
        re.compile(data['pattern'])
    except re.error as e:
        return jsonify({'success': False, 'message': f'正则表达式格式错误: {str(e)}'}), 400

    try:
        rule_id = TrafficRuleModel.create(data)
        return jsonify({'success': True, 'message': '规则添加成功', 'data': {'id': rule_id}})
    except Exception as e:
        return jsonify({'success': False, 'message': f'添加失败: {str(e)}'}), 500


@monitor_bp.route('/traffic/rules/<int:rule_id>', methods=['PUT'])
@login_required
def update_traffic_rule(rule_id):
    """更新流量监控规则"""
    data = request.get_json()
    if 'pattern' in data:
        try:
            re.compile(data['pattern'])
        except re.error as e:
            return jsonify({'success': False, 'message': f'正则表达式格式错误: {str(e)}'}), 400
    try:
        TrafficRuleModel.update(rule_id, data)
        return jsonify({'success': True, 'message': '规则更新成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500


@monitor_bp.route('/traffic/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def delete_traffic_rule(rule_id):
    """删除流量监控规则"""
    try:
        TrafficRuleModel.delete(rule_id)
        return jsonify({'success': True, 'message': '规则删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


@monitor_bp.route('/traffic/alerts', methods=['GET'])
@login_required
def get_traffic_alerts():
    """获取流量告警记录"""
    server_id = request.args.get('server_id', type=int)
    limit = request.args.get('limit', 100, type=int)
    if server_id:
        alerts = TrafficAlertModel.get_by_server(server_id, limit)
    else:
        alerts = TrafficAlertModel.get_all(limit)
    return jsonify({'success': True, 'data': [dict(row) for row in alerts]})


# ==================== 流量监控启停 ====================

@monitor_bp.route('/servers/<int:server_id>/traffic/start', methods=['POST'])
@login_required
def start_traffic_monitor(server_id):
    """启动流量监控"""
    try:
        tm = get_traffic_monitor()
        result = tm.start_monitoring(server_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': f'启动失败: {str(e)}'}), 500


@monitor_bp.route('/servers/<int:server_id>/traffic/stop', methods=['POST'])
@login_required
def stop_traffic_monitor(server_id):
    """停止流量监控"""
    try:
        tm = get_traffic_monitor()
        result = tm.stop_monitoring(server_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': f'停止失败: {str(e)}'}), 500


@monitor_bp.route('/servers/<int:server_id>/traffic/status', methods=['GET'])
@login_required
def get_traffic_monitor_status(server_id):
    """获取流量监控状态"""
    config = MonitorConfigModel.get_by_server(server_id)
    if config:
        return jsonify({
            'success': True,
            'data': {'traffic_monitor_enabled': bool(config['traffic_monitor_enabled'])}
        })
    return jsonify({'success': True, 'data': {'traffic_monitor_enabled': False}})
