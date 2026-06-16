import threading
from flask import Blueprint, request, jsonify
from routes.auth_routes import login_required
from services.resource_probe import ResourceProbe

probe_bp = Blueprint('probe', __name__, url_prefix='/api')
_probe_instance = ResourceProbe()


@probe_bp.route('/probe', methods=['POST'])
@login_required
def start_probe():
    """启动资源探测"""
    data = request.get_json()

    targets_text = data.get('targets', '').strip()
    if not targets_text:
        return jsonify({'success': False, 'message': '请输入探测目标'}), 400

    # 解析目标
    ips = []
    cidrs = []
    domains = []

    for line in targets_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # CIDR 格式
        if '/' in line:
            cidrs.append(line)
        # IP 范围格式
        elif '-' in line and any(c.isdigit() for c in line):
            ips.append(line)
        # 域名（正则或普通）
        elif line.replace('.', '').replace('*', '').replace('-', '').isalpha():
            domains.append(line)
        # 单个 IP
        else:
            ips.append(line)

    # 白名单
    whitelist = []
    whitelist_text = data.get('whitelist', '').strip()
    if whitelist_text:
        whitelist = [line.strip() for line in whitelist_text.split('\n') if line.strip()]

    # 端口
    ports = data.get('ports', [80, 8080, 443])

    # 后台线程执行探测
    def run_probe():
        _probe_instance.probe_targets(
            {'ips': ips, 'cidrs': cidrs, 'domains': domains},
            whitelist=whitelist,
            ports=ports
        )

    thread = threading.Thread(target=run_probe, daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': '探测已启动'})


@probe_bp.route('/probe/results', methods=['GET'])
@login_required
def get_probe_results():
    """获取探测结果"""
    results = _probe_instance.get_results()
    progress = _probe_instance.get_progress()
    return jsonify({
        'success': True,
        'data': {
            'results': results,
            'progress': progress
        }
    })
