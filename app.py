from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO
from database.db import init_db
from routes import register_blueprints
from routes.auth_routes import login_required, init_default_admin
import config

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'

# 初始化 SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 注册蓝图
register_blueprints(app)

# 初始化数据库
init_db()

# 初始化默认管理员
init_default_admin()

# 初始化默认流量监控规则
from database.models import TrafficRuleModel
def init_default_traffic_rules():
    existing = TrafficRuleModel.get_all()
    if len(existing) == 0:
        for rule in config.DEFAULT_TRAFFIC_RULES:
            TrafficRuleModel.create(rule)
        print(f"[初始化] 已创建 {len(config.DEFAULT_TRAFFIC_RULES)} 条默认流量监控规则")

init_default_traffic_rules()


@app.route('/')
def index():
    """主页 - 需要登录"""
    if not request.args.get('no_redirect') and not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if not app.config.get('TESTING'):
            pass  # 前端会处理登录检查
    return render_template('index.html')


@app.route('/login')
def login_page():
    """登录页面"""
    return render_template('login.html')


# 全局错误处理
@app.errorhandler(404)
def not_found(error):
    if request.is_json:
        return jsonify({'success': False, 'message': '接口不存在'}), 404
    return render_template('index.html'), 404


@app.errorhandler(500)
def internal_error(error):
    if request.is_json:
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    return render_template('index.html'), 500


if __name__ == '__main__':
    print(f"=" * 60)
    print(f"AWD 防御运维工作台")
    print(f"访问地址: http://{config.FLASK_HOST}:{config.FLASK_PORT}")
    print(f"=" * 60)
    socketio.run(
        app,
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        allow_unsafe_werkzeug=True
    )
