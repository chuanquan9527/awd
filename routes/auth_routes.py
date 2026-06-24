from functools import wraps
from flask import Blueprint, request, jsonify, session, redirect, url_for
from database.models import UserModel
from database.db import init_db
import config

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'success': False, 'message': '未登录，请先登录'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function


def init_default_admin():
    """首次启动时初始化默认管理员账户"""
    if UserModel.count() == 0:
        if config.ADMIN_PASSWORD:
            if not config.PASSWORD_PATTERN.match(config.ADMIN_PASSWORD):
                print(f"[警告] 环境变量 AWD_ADMIN_PASS 中的密码不符合强密码策略要求")
                print(f"[提示] {config.PASSWORD_HINT}")
                return False
            UserModel.create(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)
            print(f"[初始化] 已创建默认管理员账户: {config.ADMIN_USERNAME}")
            return True
        else:
            print("[警告] 未设置管理员初始密码，请通过环境变量 AWD_ADMIN_PASS 设置")
            print("[提示] 密码必须至少 12 位，包含大小写字母、数字和特殊字符")
            return False
    return True


@auth_bp.route('/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

    user = UserModel.get_by_username(username)

    # 检查账户是否被锁定
    if user and UserModel.is_locked(user):
        locked_until = user['locked_until']
        return jsonify({
            'success': False,
            'message': f'账户已被锁定，请稍后再试。锁定至: {locked_until}'
        }), 403

    # 验证密码
    if not user or not UserModel.verify_password(user, password):
        if user:
            UserModel.increment_login_attempts(user['id'])
            # 检查是否需要锁定
            updated_user = UserModel.get_by_id(user['id'])
            if updated_user['login_attempts'] >= config.MAX_LOGIN_ATTEMPTS:
                UserModel.lock_account(user['id'], config.LOCKOUT_DURATION_MINUTES)
                return jsonify({
                    'success': False,
                    'message': f'连续 {config.MAX_LOGIN_ATTEMPTS} 次登录失败，账户已锁定 {config.LOCKOUT_DURATION_MINUTES} 分钟'
                }), 403
        return jsonify({'success': False, 'message': '用户名或密码错误'}), 401

    # 登录成功，重置失败计数
    UserModel.reset_login_attempts(user['id'])
    session['logged_in'] = True
    session['user_id'] = user['id']
    session['username'] = user['username']

    return jsonify({
        'success': True,
        'message': '登录成功',
        'data': {'username': user['username']}
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """用户退出"""
    session.clear()
    return jsonify({'success': True, 'message': '已退出登录'})


@auth_bp.route('/check', methods=['GET'])
def check_auth():
    """检查登录状态"""
    if session.get('logged_in'):
        return jsonify({
            'success': True,
            'logged_in': True,
            'username': session.get('username', '')
        })
    return jsonify({'success': True, 'logged_in': False})


@auth_bp.route('/password', methods=['PUT'])
@login_required
def change_password():
    """修改密码"""
    data = request.get_json()
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return jsonify({'success': False, 'message': '旧密码和新密码不能为空'}), 400

    # 验证新密码强度
    if not config.PASSWORD_PATTERN.match(new_password):
        return jsonify({
            'success': False,
            'message': config.PASSWORD_HINT
        }), 400

    user = UserModel.get_by_id(session['user_id'])
    if not UserModel.verify_password(user, old_password):
        return jsonify({'success': False, 'message': '旧密码错误'}), 401

    UserModel.update_password(user['id'], new_password)
    return jsonify({'success': True, 'message': '密码修改成功'})
