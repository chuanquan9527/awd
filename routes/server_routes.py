from flask import Blueprint, request, jsonify
from routes.auth_routes import login_required
from database.models import ServerModel
from services.ssh_manager import SSHManager
import json

server_bp = Blueprint('server', __name__, url_prefix='/api')
ssh_manager = SSHManager()


@server_bp.route('/servers', methods=['GET'])
@login_required
def get_servers():
    """获取所有服务器列表"""
    servers = ServerModel.get_all()
    return jsonify({
        'success': True,
        'data': [dict(row) for row in servers]
    })


@server_bp.route('/servers', methods=['POST'])
@login_required
def add_server():
    """添加服务器"""
    data = request.get_json()

    required_fields = ['name', 'host', 'username', 'password']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'success': False, 'message': f'缺少必填字段: {field}'}), 400

    try:
        server_id = ServerModel.create(data)
        return jsonify({
            'success': True,
            'message': '服务器添加成功',
            'data': {'id': server_id}
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'添加失败: {str(e)}'}), 500


@server_bp.route('/servers/<int:server_id>', methods=['PUT'])
@login_required
def update_server(server_id):
    """更新服务器信息"""
    data = request.get_json()
    ServerModel.update(server_id, data)
    return jsonify({'success': True, 'message': '更新成功'})


@server_bp.route('/servers/<int:server_id>', methods=['DELETE'])
@login_required
def delete_server(server_id):
    """删除服务器"""
    # 关闭 SSH 连接
    ssh_manager.close_connection(server_id)
    ServerModel.delete(server_id)
    return jsonify({'success': True, 'message': '删除成功'})


@server_bp.route('/servers/<int:server_id>/connect', methods=['POST'])
@login_required
def connect_server(server_id):
    """连接服务器并采集信息（支持分步状态检测）"""
    server_row = ServerModel.get_by_id(server_id)
    if not server_row:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404

    server = dict(server_row)

    try:
        # 步骤1: 测试 SSH 连接
        success, message = ssh_manager.test_connection(
            server['host'], server['port'], server['username'], server['password']
        )
        if not success:
            return jsonify({
                'success': False,
                'message': f'连接失败: {message}',
                'step': 'ssh_connect',
                'step_status': 'error'
            }), 400

        # 建立连接
        ssh_manager.get_connection(server_id, server['host'], server['port'],
                                    server['username'], server['password'])

        from services.server_info import ServerInfoCollector
        collector = ServerInfoCollector(ssh_manager)

        # 步骤2: 采集基本信息
        info = collector.collect_all(server_id)

        # 步骤3: 采集详细信息（参考 awd_info_collect.sh 的分类）
        detailed = collector.collect_detailed_info(server_id)
        info.update(detailed)

        # 步骤4: 检查网站根目录
        web_root_status = collector.check_web_root(server_id, server.get('web_root', '/var/www/html'))
        info['web_root_status'] = web_root_status

        # 步骤5: 检查 MySQL 连接（仅当配置了数据库信息时）
        db_user = server.get('db_user', '')
        db_password = server.get('db_password', '')
        db_name = server.get('db_name', '')
        if db_user and db_password:
            mysql_conn_status = collector.check_mysql_connection(
                server_id, db_user, db_password, db_name
            )
        else:
            mysql_conn_status = 'not_configured'
        info['mysql_conn_status'] = mysql_conn_status

        # 更新数据库
        ServerModel.update_info(server_id, info)

        return jsonify({
            'success': True,
            'message': '连接成功，信息已更新',
            'data': info,
            'steps': {
                'ssh_connect': 'done',
                'basic_info': 'done',
                'web_root_check': web_root_status,
                'mysql_check': mysql_conn_status
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'采集信息失败: {str(e)}',
            'step': 'unknown',
            'step_status': 'error'
        }), 500


@server_bp.route('/servers/<int:server_id>/connect-step', methods=['POST'])
@login_required
def connect_server_step(server_id):
    """分步连接服务器，前端轮询用"""
    server_row = ServerModel.get_by_id(server_id)
    if not server_row:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404

    server = dict(server_row)
    step = request.json.get('step', 'ssh_connect')

    try:
        if step == 'ssh_connect':
            success, message = ssh_manager.test_connection(
                server['host'], server['port'], server['username'], server['password']
            )
            if not success:
                return jsonify({
                    'success': False,
                    'message': f'SSH连接失败: {message}',
                    'current_step': 'ssh_connect',
                    'step_status': 'error'
                }), 400
            ssh_manager.get_connection(server_id, server['host'], server['port'],
                                        server['username'], server['password'])
            return jsonify({
                'success': True,
                'message': 'SSH连接成功',
                'current_step': 'ssh_connect',
                'next_step': 'basic_info',
                'step_status': 'done'
            })

        elif step == 'basic_info':
            from services.server_info import ServerInfoCollector
            collector = ServerInfoCollector(ssh_manager)
            info = collector.collect_all(server_id)
            # 暂存到内存或临时字段，这里直接返回给前端
            return jsonify({
                'success': True,
                'message': '基本信息采集完成',
                'current_step': 'basic_info',
                'next_step': 'web_root_check',
                'step_status': 'done',
                'data': info
            })

        elif step == 'web_root_check':
            from services.server_info import ServerInfoCollector
            collector = ServerInfoCollector(ssh_manager)
            web_root_status = collector.check_web_root(server_id, server.get('web_root', '/var/www/html'))
            return jsonify({
                'success': True,
                'message': f'网站根目录检查完成: {web_root_status}',
                'current_step': 'web_root_check',
                'next_step': 'mysql_check',
                'step_status': 'done',
                'web_root_status': web_root_status
            })

        elif step == 'mysql_check':
            from services.server_info import ServerInfoCollector
            collector = ServerInfoCollector(ssh_manager)
            db_user = server.get('db_user', '')
            db_password = server.get('db_password', '')
            db_name = server.get('db_name', '')
            if db_user and db_password:
                mysql_conn_status = collector.check_mysql_connection(
                    server_id, db_user, db_password, db_name
                )
            else:
                mysql_conn_status = 'not_configured'
            return jsonify({
                'success': True,
                'message': f'MySQL连接检查完成: {mysql_conn_status}',
                'current_step': 'mysql_check',
                'next_step': 'finish',
                'step_status': 'done',
                'mysql_conn_status': mysql_conn_status
            })

        elif step == 'finish':
            # 最终保存所有信息（包括详细分类信息）
            from services.server_info import ServerInfoCollector
            collector = ServerInfoCollector(ssh_manager)
            info = collector.collect_all(server_id)
            info['web_root_status'] = request.json.get('web_root_status', 'unknown')
            info['mysql_conn_status'] = request.json.get('mysql_conn_status', 'unknown')
            # 采集详细信息
            detailed = collector.collect_detailed_info(server_id)
            info.update(detailed)
            ServerModel.update_info(server_id, info)
            return jsonify({
                'success': True,
                'message': '服务器信息已保存',
                'current_step': 'finish',
                'step_status': 'done',
                'data': info
            })

        else:
            return jsonify({'success': False, 'message': '未知步骤'}), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'步骤执行失败: {str(e)}',
            'current_step': step,
            'step_status': 'error'
        }), 500


@server_bp.route('/servers/<int:server_id>/refresh', methods=['POST'])
@login_required
def refresh_server(server_id):
    """刷新服务器信息"""
    return connect_server(server_id)


@server_bp.route('/servers/<int:server_id>/info', methods=['GET'])
@login_required
def get_server_info(server_id):
    """获取服务器详细信息"""
    server = ServerModel.get_by_id(server_id)
    if not server:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404

    return jsonify({
        'success': True,
        'data': dict(server)
    })


@server_bp.route('/servers/<int:server_id>/writable-dirs', methods=['GET'])
@login_required
def get_writable_dirs(server_id):
    """实时探测服务器上的可写入目录"""
    server = ServerModel.get_by_id(server_id)
    if not server:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404

    try:
        dirs_to_check = ['/tmp', '/var/tmp', '/dev/shm', '/var/www/html', '/var/www', '/home']
        writable = []
        for d in dirs_to_check:
            stdout, _, _ = ssh_manager.exec_command(
                server_id,
                f"test -w '{d}' 2>/dev/null && echo 'WRITABLE' || echo 'NO'",
                timeout=10
            )
            if stdout.strip() == 'WRITABLE':
                writable.append(d)
        return jsonify({'success': True, 'data': writable})
    except Exception as e:
        return jsonify({'success': False, 'message': f'探测失败: {str(e)}'}), 500
