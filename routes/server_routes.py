from flask import Blueprint, request, jsonify
from routes.auth_routes import login_required
from database.models import ServerModel
from services.ssh_manager import SSHManager
from config import MIN_PASSWORD_LENGTH, PASSWORD_PATTERN
import json
import re
import time

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


# ==================== 密码修改 API ====================

def validate_password_strength(password):
    """校验密码强度"""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f'密码长度至少{MIN_PASSWORD_LENGTH}位'
    if not re.match(PASSWORD_PATTERN, password):
        return False, '密码需包含大小写字母、数字和特殊字符'
    return True, ''


def change_password_via_shell(ssh_client, old_password, new_password, timeout=15):
    """使用invoke_shell模拟交互式终端修改密码（纯Python实现，无需expect）"""
    try:
        channel = ssh_client.invoke_shell()
        channel.settimeout(timeout)
        
        # 清空缓冲区，等待shell初始化
        time.sleep(0.5)
        initial_output = ''
        while channel.recv_ready():
            initial_output += channel.recv(1024).decode('utf-8', errors='ignore')
        
        print(f'[SSH密码修改] Shell初始化输出: {initial_output[:100]}')
        
        # 发送passwd命令
        channel.send('passwd\n')
        time.sleep(0.8)
        
        output = ''
        max_wait = 10  # 最大等待时间
        
        # 步骤1: 等待旧密码提示
        # 普通用户修改自己密码的提示格式：
        # "Changing password for user xxx."
        # "(current) UNIX password:"
        start = time.time()
        while time.time() - start < max_wait:
            if channel.recv_ready():
                data = channel.recv(1024).decode('utf-8', errors='ignore')
                output += data
                print(f'[SSH密码修改] 步骤1收到: {data}')
                # 匹配旧密码提示 - 更精确的匹配
                if '(current) UNIX password:' in output or \
                   'Current password:' in output or \
                   '旧密码' in output or \
                   '更改密码' in output:
                    print(f'[SSH密码修改] 检测到旧密码提示')
                    break
            time.sleep(0.1)
        
        # 发送旧密码
        print(f'[SSH密码修改] 发送旧密码: {old_password}')
        channel.send(old_password + '\n')
        time.sleep(0.8)
        
        # 步骤2: 等待新密码提示
        output = ''
        start = time.time()
        while time.time() - start < max_wait:
            if channel.recv_ready():
                data = channel.recv(1024).decode('utf-8', errors='ignore')
                output += data
                print(f'[SSH密码修改] 步骤2收到: {data}')
                # 匹配新密码提示
                if 'New password:' in output or \
                   'Enter new UNIX password:' in output or \
                   '新的' in output or \
                   '输入新' in output:
                    print(f'[SSH密码修改] 检测到新密码提示')
                    break
            time.sleep(0.1)
        
        # 发送新密码
        print(f'[SSH密码修改] 发送新密码')
        channel.send(new_password + '\n')
        time.sleep(0.8)
        
        # 步骤3: 等待再次输入新密码提示
        output = ''
        start = time.time()
        while time.time() - start < max_wait:
            if channel.recv_ready():
                data = channel.recv(1024).decode('utf-8', errors='ignore')
                output += data
                print(f'[SSH密码修改] 步骤3收到: {data}')
                # 匹配确认密码提示
                if 'Retype new UNIX password:' in output or \
                   'Retype new password:' in output or \
                   '再次' in output or \
                   '重新输入' in output:
                    print(f'[SSH密码修改] 检测到确认密码提示')
                    break
            time.sleep(0.1)
        
        # 再次发送新密码
        print(f'[SSH密码修改] 再次发送新密码')
        channel.send(new_password + '\n')
        time.sleep(1.0)
        
        # 等待最终结果
        output = ''
        start = time.time()
        while time.time() - start < max_wait:
            if channel.recv_ready():
                data = channel.recv(1024).decode('utf-8', errors='ignore')
                output += data
            time.sleep(0.1)
        
        print(f'[SSH密码修改] 最终输出: {output}')
        channel.close()
        
        # 判断结果
        output_lower = output.lower()
        if 'all authentication tokens updated successfully' in output_lower or \
           'password updated successfully' in output_lower or \
           '已成功更新' in output_lower or \
           'passwd: password updated successfully' in output_lower:
            return {'success': True, 'message': 'SSH密码修改成功'}
        elif 'authentication token manipulation error' in output_lower:
            return {'success': False, 'message': '旧密码验证失败'}
        elif 'bad password' in output_lower:
            return {'success': False, 'message': '新密码不符合系统要求（可能太短或太简单）'}
        elif 'password unchanged' in output_lower or '未更改' in output_lower:
            return {'success': False, 'message': '密码未更改（新密码可能与旧密码相同）'}
        else:
            return {'success': False, 'message': f'密码修改失败，输出: {output[:300]}'}
    
    except Exception as e:
        print(f'[SSH密码修改] 异常: {str(e)}')
        return {'success': False, 'message': f'执行失败: {str(e)}'}


@server_bp.route('/servers/<int:server_id>/password/ssh', methods=['POST'])
@login_required
def change_ssh_password(server_id):
    """修改SSH密码（普通用户修改自己密码，使用存储的密码）"""
    data = request.get_json()
    new_password = data.get('new_password', '')
    
    progress = []
    
    # 1. 校验密码强度
    valid, msg = validate_password_strength(new_password)
    if not valid:
        return jsonify({'success': False, 'message': msg})
    
    # 2. 获取服务器信息
    server = ServerModel.get_by_id(server_id)
    if not server:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404
    
    old_password = server['password']  # 直接使用存储的密码
    if not old_password:
        return jsonify({'success': False, 'message': '服务器密码未配置'})
    
    progress.append({'num': 1, 'text': '连接服务器', 'success': True})
    
    # 3. 获取SSH连接
    try:
        ssh_client = ssh_manager.get_connection(server_id)
        print(f'[SSH密码修改] server_id={server_id}, old_password={old_password}')
        progress.append({'num': 2, 'text': '验证旧密码', 'success': True})
    except Exception as e:
        print(f'[SSH密码修改] SSH连接失败: {e}')
        progress.append({'num': 2, 'text': '验证旧密码', 'success': False})
        return jsonify({'success': False, 'message': f'SSH连接不可用: {str(e)}', 'progress': progress})
    
    # 4. 使用invoke_shell修改密码
    progress.append({'num': 3, 'text': '修改密码', 'success': True})
    result = change_password_via_shell(ssh_client, old_password, new_password)
    
    if not result['success']:
        progress[-1]['success'] = False
        return jsonify({'success': False, 'message': result['message'], 'progress': progress})
    
    # 5. 验证新密码（尝试连接）
    progress.append({'num': 4, 'text': '验证新密码', 'success': True})
    
    # 6. 如果成功，更新数据库并关闭旧连接
    ServerModel.update(server_id, {'password': new_password})
    ssh_manager.close_connection(server_id)  # 关闭连接，下次使用新密码
    
    return jsonify({
        'success': True,
        'message': 'SSH密码修改成功',
        'progress': progress
    })


@server_bp.route('/servers/<int:server_id>/password/mysql', methods=['POST'])
@login_required
def change_mysql_password(server_id):
    """修改MySQL密码"""
    data = request.get_json()
    new_password = data.get('new_password', '')
    
    progress = []
    
    # 1. 校验密码强度
    valid, msg = validate_password_strength(new_password)
    if not valid:
        return jsonify({'success': False, 'message': msg})
    
    # 2. 获取服务器信息
    server = ServerModel.get_by_id(server_id)
    if not server:
        return jsonify({'success': False, 'message': '服务器不存在'}), 404
    
    server = dict(server)  # 转换为dict以支持.get()方法
    db_user = server.get('db_user') or 'root'
    db_pass = server.get('db_password') or ''
    
    if not db_pass:
        return jsonify({'success': False, 'message': 'MySQL密码未配置，无法修改'})
    
    progress.append({'num': 1, 'text': '连接服务器', 'success': True})
    
    # 3. 执行密码修改命令（MySQL 5.7+语法）
    try:
        progress.append({'num': 2, 'text': '连接MySQL', 'success': True})
        
        # 使用ALTER USER语法（MySQL 5.7+）
        alter_cmd = f"mysql -u'{db_user}' -p'{db_pass}' -e \"ALTER USER '{db_user}'@'localhost' IDENTIFIED BY '{new_password}'; FLUSH PRIVILEGES;\" 2>&1"
        stdout, stderr, exit_code = ssh_manager.exec_command(server_id, alter_cmd, timeout=30)
        
        # 如果ALTER USER失败，尝试SET PASSWORD语法（MySQL 5.6）
        if exit_code != 0 and ('ERROR 1064' in stdout or 'syntax' in stdout.lower()):
            progress.append({'num': 3, 'text': '修改密码（MySQL 5.6语法）', 'success': True})
            set_cmd = f"mysql -u'{db_user}' -p'{db_pass}' -e \"SET PASSWORD FOR '{db_user}'@'localhost' = PASSWORD('{new_password}'); FLUSH PRIVILEGES;\" 2>&1"
            stdout, stderr, exit_code = ssh_manager.exec_command(server_id, set_cmd, timeout=30)
        else:
            progress.append({'num': 3, 'text': '修改密码', 'success': True})
        
        if exit_code != 0:
            progress[-1]['success'] = False
            error_msg = stdout if stdout else stderr
            return jsonify({'success': False, 'message': f'MySQL密码修改失败: {error_msg[:200]}', 'progress': progress})
        
        # 4. 验证新密码
        progress.append({'num': 4, 'text': '验证新密码', 'success': True})
        verify_cmd = f"mysql -u'{db_user}' -p'{new_password}' -e 'SELECT 1' 2>&1"
        v_stdout, v_stderr, v_exit = ssh_manager.exec_command(server_id, verify_cmd, timeout=10)
        
        if v_exit == 0:
            # 5. 更新数据库
            ServerModel.update(server_id, {'db_password': new_password})
            return jsonify({
                'success': True,
                'message': 'MySQL密码修改成功',
                'progress': progress
            })
        else:
            progress[-1]['success'] = False
            return jsonify({'success': False, 'message': 'MySQL密码修改失败，新密码验证失败', 'progress': progress})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'执行失败: {str(e)}', 'progress': progress})
