from flask import Blueprint

# 创建蓝图
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
server_bp = Blueprint('server', __name__, url_prefix='/api')
backup_bp = Blueprint('backup', __name__, url_prefix='/api')
monitor_bp = Blueprint('monitor', __name__, url_prefix='/api')


def register_blueprints(app):
    """注册所有蓝图到 Flask 应用"""
    from routes.auth_routes import auth_bp
    from routes.server_routes import server_bp
    from routes.backup_routes import backup_bp
    from routes.monitor_routes import monitor_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(server_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(monitor_bp)