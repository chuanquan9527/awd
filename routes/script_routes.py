from flask import Blueprint, request, jsonify

from database.models import ScriptModel
from routes.auth_routes import login_required
from services.script_deploy import ScriptDeployManager, parse_remove_files
from services.ssh_manager import SSHManager


script_bp = Blueprint('script', __name__, url_prefix='/api')
ssh_manager = SSHManager()
script_manager = ScriptDeployManager(ssh_manager)


@script_bp.route('/scripts', methods=['GET'])
@login_required
def list_scripts():
    """获取脚本列表"""
    try:
        scripts = ScriptModel.get_all()
        return jsonify({'success': True, 'data': scripts})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取脚本列表失败: {str(e)}'}), 500


@script_bp.route('/scripts/<int:script_id>', methods=['GET'])
@login_required
def get_script(script_id):
    """获取脚本详情"""
    script = ScriptModel.get_by_id(script_id)
    if not script:
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    return jsonify({'success': True, 'data': script})


@script_bp.route('/scripts', methods=['POST'])
@login_required
def create_script():
    """创建脚本"""
    data = request.form.to_dict()
    uploaded_files = request.files.getlist('files')

    try:
        script = script_manager.create_script(data, uploaded_files)
        return jsonify({'success': True, 'message': '脚本创建成功', 'data': script})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        msg = str(e)
        if 'UNIQUE constraint failed' in msg:
            return jsonify({'success': False, 'message': '脚本名称已存在'}), 400
        return jsonify({'success': False, 'message': f'脚本创建失败: {msg}'}), 500


@script_bp.route('/scripts/<int:script_id>', methods=['PUT'])
@login_required
def update_script(script_id):
    """更新脚本"""
    data = request.form.to_dict()
    uploaded_files = request.files.getlist('files')
    remove_files = parse_remove_files(data.pop('remove_files', ''))

    try:
        script = script_manager.update_script(script_id, data, uploaded_files, remove_files)
        if not script:
            return jsonify({'success': False, 'message': '脚本不存在'}), 404
        return jsonify({'success': True, 'message': '脚本更新成功', 'data': script})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        msg = str(e)
        if 'UNIQUE constraint failed' in msg:
            return jsonify({'success': False, 'message': '脚本名称已存在'}), 400
        return jsonify({'success': False, 'message': f'脚本更新失败: {msg}'}), 500


@script_bp.route('/scripts/<int:script_id>', methods=['DELETE'])
@login_required
def delete_script(script_id):
    """删除脚本及本地文件"""
    try:
        deleted = script_manager.delete_script(script_id)
        if not deleted:
            return jsonify({'success': False, 'message': '脚本不存在'}), 404
        return jsonify({'success': True, 'message': '脚本已删除'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'脚本删除失败: {str(e)}'}), 500


@script_bp.route('/servers/<int:server_id>/scripts/<int:script_id>/deploy', methods=['POST'])
@login_required
def deploy_script(server_id, script_id):
    """部署脚本到指定服务器"""
    try:
        result = script_manager.deploy(server_id, script_id)
        status_code = 200 if result.get('success') else 400
        return jsonify({
            'success': result.get('success', False),
            'message': result.get('message', ''),
            'data': result,
        }), status_code
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'脚本部署失败: {str(e)}'}), 500
