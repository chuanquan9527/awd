import json
import os
import posixpath
import shutil
import shlex
import tarfile
import time

from werkzeug.utils import secure_filename

from config import (
    SCRIPT_ALLOWED_TYPES,
    SCRIPT_DEPLOY_TIMEOUT,
    SCRIPT_MAX_FILE_SIZE_MB,
    SCRIPT_STORAGE_DIR,
)
from database.models import ScriptModel, ServerModel


class ScriptDeployManager:
    """脚本部署管理器 - 管理脚本元数据、本地文件和远程部署。"""

    FORBIDDEN_REMOTE_DIRS = {'/', '/root'}

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager
        os.makedirs(SCRIPT_STORAGE_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # 路径与校验
    # ------------------------------------------------------------------
    def _script_dir(self, script_id):
        return os.path.join(SCRIPT_STORAGE_DIR, str(script_id))

    def _files_dir(self, script_id):
        return os.path.join(self._script_dir(script_id), 'files')

    def _assert_inside_storage(self, path):
        root = os.path.abspath(SCRIPT_STORAGE_DIR)
        target = os.path.abspath(path)
        if target != root and not target.startswith(root + os.sep):
            raise Exception(f'非法脚本路径: {target}')
        return target

    def validate_remote_dir(self, remote_dir):
        remote_dir = (remote_dir or '/tmp').strip() or '/tmp'
        remote_dir = remote_dir.rstrip('/') or '/'
        if not remote_dir.startswith('/'):
            raise ValueError('脚本目录必须是绝对路径')
        if remote_dir in self.FORBIDDEN_REMOTE_DIRS:
            raise ValueError(f'脚本目录不允许设置为 {remote_dir}')
        if '\x00' in remote_dir or "'" in remote_dir:
            raise ValueError('脚本目录包含非法字符')
        return remote_dir

    def _quote(self, value):
        return shlex.quote(str(value))

    def normalize_deploy_script(self, deploy_script):
        # Deployment scripts run on Linux targets; normalize Windows CRLF input early.
        return (deploy_script or '').replace('\r\n', '\n').replace('\r', '\n')

    def validate_payload(self, data, partial=False):
        cleaned = {}

        if not partial or 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                raise ValueError('脚本名称不能为空')
            if len(name) > 64:
                raise ValueError('脚本名称不能超过 64 个字符')
            if any(ch in name for ch in ('/', '\\', '\x00')):
                raise ValueError('脚本名称不能包含路径分隔符')
            cleaned['name'] = name

        if not partial or 'script_type' in data:
            script_type = (data.get('script_type') or '').strip().lower()
            if script_type not in SCRIPT_ALLOWED_TYPES:
                raise ValueError('脚本类型仅支持 php 或 shell')
            cleaned['script_type'] = script_type

        if 'description' in data or not partial:
            description = (data.get('description') or '').strip()
            if len(description) > 500:
                raise ValueError('脚本描述不能超过 500 个字符')
            cleaned['description'] = description

        if 'remote_dir' in data or not partial:
            cleaned['remote_dir'] = self.validate_remote_dir(data.get('remote_dir') or '/tmp')

        if not partial or 'deploy_script' in data:
            deploy_script = self.normalize_deploy_script(data.get('deploy_script') or '')
            if not deploy_script.strip():
                raise ValueError('部署脚本不能为空')
            if len(deploy_script) > 20000:
                raise ValueError('部署脚本不能超过 20000 个字符')
            cleaned['deploy_script'] = deploy_script

        return cleaned

    # ------------------------------------------------------------------
    # 本地文件管理
    # ------------------------------------------------------------------
    def save_uploaded_files(self, script_id, uploaded_files, existing_files=None):
        existing_files = existing_files or []
        files_by_name = {item['filename']: item for item in existing_files if item.get('filename')}
        files_dir = self._files_dir(script_id)
        self._assert_inside_storage(files_dir)
        os.makedirs(files_dir, exist_ok=True)

        max_size = SCRIPT_MAX_FILE_SIZE_MB * 1024 * 1024
        for storage in uploaded_files or []:
            if not storage or not storage.filename:
                continue
            filename = secure_filename(os.path.basename(storage.filename))
            if not filename:
                raise ValueError('上传文件名非法')

            target_path = os.path.join(files_dir, filename)
            self._assert_inside_storage(target_path)
            storage.save(target_path)

            size = os.path.getsize(target_path)
            if size == 0:
                os.remove(target_path)
                raise ValueError(f'上传文件不能为空: {filename}')
            if size > max_size:
                os.remove(target_path)
                raise ValueError(f'上传文件超过 {SCRIPT_MAX_FILE_SIZE_MB} MB: {filename}')

            files_by_name[filename] = {
                'filename': filename,
                'size': size,
                'relative_path': f'files/{filename}'
            }

        return sorted(files_by_name.values(), key=lambda item: item['filename'].lower())

    def remove_files(self, script_id, filenames, existing_files):
        if not filenames:
            return existing_files

        remove_set = {secure_filename(os.path.basename(name)) for name in filenames if name}
        files_dir = self._files_dir(script_id)
        kept = []
        for item in existing_files:
            filename = item.get('filename')
            if filename in remove_set:
                target_path = os.path.join(files_dir, filename)
                self._assert_inside_storage(target_path)
                if os.path.exists(target_path):
                    os.remove(target_path)
            else:
                kept.append(item)
        return kept

    def write_deploy_script(self, script_id, deploy_script):
        script_dir = self._script_dir(script_id)
        self._assert_inside_storage(script_dir)
        os.makedirs(script_dir, exist_ok=True)
        path = os.path.join(script_dir, 'deploy.sh')
        self._assert_inside_storage(path)
        deploy_script = self.normalize_deploy_script(deploy_script)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(deploy_script)
        return path

    def create_script(self, data, uploaded_files):
        payload = self.validate_payload(data)
        payload['files'] = []
        script_id = ScriptModel.create(payload)
        try:
            files = self.save_uploaded_files(script_id, uploaded_files, [])
            self.write_deploy_script(script_id, payload['deploy_script'])
            ScriptModel.update(script_id, {'files': files})
            return ScriptModel.get_by_id(script_id)
        except Exception:
            self.delete_script(script_id, missing_ok=True)
            raise

    def update_script(self, script_id, data, uploaded_files, remove_files=None):
        script = ScriptModel.get_by_id(script_id)
        if not script:
            return None

        payload = self.validate_payload(data, partial=True)
        files = list(script.get('files') or [])
        files = self.remove_files(script_id, remove_files or [], files)
        files = self.save_uploaded_files(script_id, uploaded_files, files)
        payload['files'] = files

        if 'deploy_script' in payload:
            self.write_deploy_script(script_id, payload['deploy_script'])

        ScriptModel.update(script_id, payload)
        return ScriptModel.get_by_id(script_id)

    def delete_script(self, script_id, missing_ok=False):
        script = ScriptModel.get_by_id(script_id)
        if not script and not missing_ok:
            return None

        script_dir = self._script_dir(script_id)
        self._assert_inside_storage(script_dir)
        if os.path.exists(script_dir):
            shutil.rmtree(script_dir)
        ScriptModel.delete(script_id)
        return True

    # ------------------------------------------------------------------
    # 远程部署
    # ------------------------------------------------------------------
    def _build_local_tar(self, script):
        script_id = script['id']
        script_dir = self._script_dir(script_id)
        self._assert_inside_storage(script_dir)
        deploy_path = os.path.join(script_dir, 'deploy.sh')
        self.write_deploy_script(script_id, script.get('deploy_script') or '')

        timestamp = int(time.time())
        tar_path = os.path.join(SCRIPT_STORAGE_DIR, f'_deploy_script_{script_id}_{timestamp}.tar')
        self._assert_inside_storage(tar_path)

        with tarfile.open(tar_path, 'w') as tar:
            tar.add(deploy_path, arcname='deploy.sh')
            for item in script.get('files') or []:
                filename = item.get('filename')
                if not filename:
                    continue
                local_path = os.path.join(self._files_dir(script_id), filename)
                self._assert_inside_storage(local_path)
                if os.path.isfile(local_path):
                    tar.add(local_path, arcname=f'files/{filename}')
        return tar_path, timestamp

    def deploy(self, server_id, script_id):
        server = ServerModel.get_by_id(server_id)
        if not server:
            raise ValueError('服务器不存在')

        script = ScriptModel.get_by_id(script_id)
        if not script:
            raise ValueError('脚本不存在')

        remote_dir = self.validate_remote_dir(script.get('remote_dir') or '/tmp')
        local_tar, timestamp = self._build_local_tar(script)
        remote_name = f'awd_script_{script_id}_{timestamp}'
        remote_tmp = posixpath.join(remote_dir, f'{remote_name}.tar')
        remote_extract_dir = posixpath.join(remote_dir, remote_name)
        uploaded = False
        extracted = False

        try:
            q_remote_dir = self._quote(remote_dir)
            q_remote_tmp = self._quote(remote_tmp)
            q_remote_extract_dir = self._quote(remote_extract_dir)
            mkdir_cmd = f"mkdir -p {q_remote_dir} && test -w {q_remote_dir}"
            _, stderr, code = self.ssh.exec_command(server_id, mkdir_cmd, timeout=30)
            if code != 0:
                raise Exception(f'脚本目录不可写: {stderr or remote_dir}')

            self.ssh.upload_file(server_id, local_tar, remote_tmp)
            uploaded = True

            extract_cmd = f"mkdir -p {q_remote_extract_dir} && tar xf {q_remote_tmp} -C {q_remote_extract_dir}"
            stdout, stderr, code = self.ssh.exec_command(server_id, extract_cmd, timeout=60)
            if code != 0:
                raise Exception(f'解压脚本包失败: {stderr or stdout}')
            extracted = True

            web_root = server['web_root'] or '/var/www/html'
            q_web_root = self._quote(web_root)
            deploy_cmd = (
                f"cd {q_remote_extract_dir} && "
                f"tr -d '\\r' < deploy.sh > .deploy.sh.lf && "
                f"mv .deploy.sh.lf deploy.sh && "
                f"chmod +x deploy.sh && "
                f"bash deploy.sh {q_web_root} {q_remote_extract_dir}"
            )
            stdout, stderr, code = self.ssh.exec_command(
                server_id,
                deploy_cmd,
                timeout=SCRIPT_DEPLOY_TIMEOUT,
            )
            return {
                'success': code == 0,
                'status': 'success' if code == 0 else 'deploy_failed',
                'message': '脚本部署成功' if code == 0 else f'脚本执行失败，退出码: {code}',
                'script_id': script_id,
                'script_name': script['name'],
                'remote_dir': remote_dir,
                'remote_extract_dir': remote_extract_dir,
                'exit_code': code,
                'stdout': stdout,
                'stderr': stderr,
            }
        except Exception:
            if uploaded and not extracted:
                self.ssh.exec_command(server_id, f"rm -f {self._quote(remote_tmp)} 2>/dev/null", timeout=10)
                self.ssh.exec_command(server_id, f"rm -rf {self._quote(remote_extract_dir)} 2>/dev/null", timeout=10)
            raise
        finally:
            try:
                os.remove(local_tar)
            except Exception:
                pass
            if uploaded:
                self.ssh.exec_command(server_id, f"rm -f {self._quote(remote_tmp)} 2>/dev/null", timeout=10)


def parse_remove_files(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []
