import os
from flask import Blueprint, request, jsonify
from routes.auth_routes import login_required
from database.models import ServerModel, BackupModel
from services.ssh_manager import SSHManager
from services.backup import WebBackup
from services.database_backup import DatabaseBackup
from services.waf_deploy import WAFManager

backup_bp = Blueprint('backup', __name__, url_prefix='/api')
ssh_manager = SSHManager()
web_backup = WebBackup(ssh_manager)
db_backup = DatabaseBackup(ssh_manager)
waf_deploy = WAFManager(ssh_manager)


# ==================== 网站备份恢复 ====================

@backup_bp.route('/servers/<int:server_id>/backup/web', methods=['POST'])
@login_required
def backup_web(server_id):
    """网站备份"""
    data = request.get_json()
    version_tag = data.get('version_tag', '').strip()
    storage_dir = data.get('storage_dir', '').strip() or '/tmp'
    clean_remote = data.get('clean_remote', False)

    if not version_tag:
        return jsonify({'success': False, 'message': '请输入版本标签'}), 400

    try:
        result = web_backup.backup(server_id, version_tag, storage_dir, clean_remote)
        return jsonify({'success': True, 'message': '网站备份成功', 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'备份失败: {str(e)}'}), 500


@backup_bp.route('/servers/<int:server_id>/restore/web/<int:backup_id>', methods=['POST'])
@login_required
def restore_web(server_id, backup_id):
    """网站恢复"""
    try:
        result = web_backup.restore(server_id, backup_id)
        return jsonify({'success': True, 'message': result['message']})
    except Exception as e:
        return jsonify({'success': False, 'message': f'恢复失败: {str(e)}'}), 500


# ==================== 数据库备份恢复 ====================

@backup_bp.route('/servers/<int:server_id>/backup/database', methods=['POST'])
@login_required
def backup_database(server_id):
    """数据库备份"""
    data = request.get_json()
    version_tag = data.get('version_tag', '').strip()
    db_name = data.get('db_name', '').strip() or None

    if not version_tag:
        return jsonify({'success': False, 'message': '请输入版本标签'}), 400

    try:
        result = db_backup.backup(server_id, version_tag, db_name)
        return jsonify({'success': True, 'message': '数据库备份成功', 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'备份失败: {str(e)}'}), 500


@backup_bp.route('/servers/<int:server_id>/restore/database/<int:backup_id>', methods=['POST'])
@login_required
def restore_database(server_id, backup_id):
    """数据库恢复"""
    try:
        result = db_backup.restore(server_id, backup_id)
        return jsonify({'success': True, 'message': result['message']})
    except Exception as e:
        return jsonify({'success': False, 'message': f'恢复失败: {str(e)}'}), 500


# ==================== 备份列表 ====================

@backup_bp.route('/servers/<int:server_id>/backups', methods=['GET'])
@login_required
def get_backups(server_id):
    """获取备份列表"""
    backup_type = request.args.get('type')
    backups = BackupModel.get_by_server(server_id, backup_type)
    return jsonify({
        'success': True,
        'data': [dict(row) for row in backups]
    })


@backup_bp.route('/backups/<int:backup_id>', methods=['DELETE'])
@login_required
def delete_backup(backup_id):
    """删除本地备份"""
    try:
        web_backup.delete_backup(backup_id, delete_local=True, delete_online=False)
        db_backup.delete_backup(backup_id, delete_local=True, delete_online=False)
        return jsonify({'success': True, 'message': '本地备份已删除'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


@backup_bp.route('/backups/<int:backup_id>/online', methods=['DELETE'])
@login_required
def delete_online_backup(backup_id):
    """删除线上临时备份文件"""
    data = request.get_json(silent=True) or {}
    server_id = data.get('server_id')

    if not server_id:
        return jsonify({'success': False, 'message': '缺少服务器ID'}), 400

    try:
        backup = BackupModel.get_by_id(backup_id)
        version_tag = backup['version_tag'] if backup else None

        # 清理线上临时文件
        search_patterns = [
            '/tmp/awd_backup_*.tar',
            '/var/tmp/awd_backup_*.tar',
            '/dev/shm/awd_backup_*.tar'
        ]
        for pattern in search_patterns:
            ssh_manager.exec_command(server_id, f'rm -f {pattern} 2>/dev/null', timeout=10)

        # 如果有版本标签，尝试精确匹配删除
        if version_tag:
            for d in ['/tmp', '/var/tmp', '/dev/shm']:
                ssh_manager.exec_command(
                    server_id,
                    f"rm -f {d}/awd_backup_*_{version_tag}_*.tar 2>/dev/null",
                    timeout=10
                )

        return jsonify({'success': True, 'message': '线上临时文件已清理'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'清理失败: {str(e)}'}), 500


# ==================== WAF 部署 ====================

@backup_bp.route('/wafs', methods=['GET'])
@login_required
def list_wafs():
    """列出本地所有可用的 WAF"""
    try:
        wafs = waf_deploy.list_wafs()
        return jsonify({'success': True, 'data': wafs})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取WAF列表失败: {str(e)}'}), 500


@backup_bp.route('/wafs/<waf_name>', methods=['GET'])
@login_required
def get_waf(waf_name):
    """获取指定 WAF 的详细信息"""
    try:
        waf = waf_deploy.get_waf(waf_name)
        if not waf:
            return jsonify({'success': False, 'message': f'WAF "{waf_name}" 不存在'}), 404
        return jsonify({'success': True, 'data': waf})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取WAF详情失败: {str(e)}'}), 500


@backup_bp.route('/servers/<int:server_id>/waf/deploy', methods=['POST'])
@login_required
def deploy_waf(server_id):
    """一键部署 WAF"""
    data = request.get_json()
    waf_name = data.get('waf_name', '').strip()
    password = data.get('password', '').strip()
    key = data.get('key', '').strip()

    if not waf_name:
        return jsonify({'success': False, 'message': '请选择要部署的 WAF'}), 400

    # 构建 extra_args: --password xxx --key yyy
    extra_args = ''
    if password:
        extra_args += f' --password {password}'
    if key:
        extra_args += f' --key {key}'
    extra_args = extra_args.strip()

    try:
        result = waf_deploy.deploy(server_id, waf_name, extra_args=extra_args)
        return jsonify({'success': True, 'message': result['message'], 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'部署失败: {str(e)}'}), 500


@backup_bp.route('/servers/<int:server_id>/waf/undeploy', methods=['POST'])
@login_required
def undeploy_waf(server_id):
    """卸载 WAF"""
    try:
        result = waf_deploy.undeploy(server_id)
        return jsonify({'success': True, 'message': result['message']})
    except Exception as e:
        return jsonify({'success': False, 'message': f'卸载失败: {str(e)}'}), 500


@backup_bp.route('/servers/<int:server_id>/waf/status', methods=['GET'])
@login_required
def waf_status(server_id):
    """检查 WAF 部署状态"""
    try:
        result = waf_deploy.verify(server_id)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'检查失败: {str(e)}'}), 500
