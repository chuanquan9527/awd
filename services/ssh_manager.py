import paramiko
import threading
import time
from config import SSH_CONNECT_TIMEOUT, SSH_COMMAND_TIMEOUT, SSH_MAX_RETRIES, SSH_RETRY_DELAY


class SSHManager:
    """SSH 连接管理器 - 单例模式"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._connections = {}  # {server_id: SSHClient}
        self._locks = {}        # {server_id: threading.Lock}
        self._initialized = True

    def _get_lock(self, server_id):
        """获取指定服务器的锁"""
        if server_id not in self._locks:
            self._locks[server_id] = threading.Lock()
        return self._locks[server_id]

    def test_connection(self, host, port, username, password, timeout=SSH_CONNECT_TIMEOUT):
        """测试 SSH 连接"""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout
            )
            client.close()
            return True, '连接成功'
        except paramiko.AuthenticationException:
            return False, '认证失败，请检查用户名和密码'
        except paramiko.SSHException as e:
            return False, f'SSH 错误: {str(e)}'
        except TimeoutError:
            return False, '连接超时'
        except Exception as e:
            return False, f'连接失败: {str(e)}'

    def get_connection(self, server_id, host=None, port=None, username=None, password=None):
        """获取或创建 SSH 连接"""
        with self._get_lock(server_id):
            # 检查现有连接是否有效
            if server_id in self._connections:
                try:
                    transport = self._connections[server_id].get_transport()
                    if transport and transport.is_active():
                        return self._connections[server_id]
                except:
                    pass
                # 连接已断开，关闭旧连接
                try:
                    self._connections[server_id].close()
                except:
                    pass
                del self._connections[server_id]

            # 需要创建新连接
            if host is None:
                from database.models import ServerModel
                server = ServerModel.get_by_id(server_id)
                if not server:
                    raise Exception('服务器不存在')
                host = server['host']
                port = server['port']
                username = server['username']
                password = server['password']

            # 重试连接
            last_error = None
            for attempt in range(SSH_MAX_RETRIES):
                try:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(
                        hostname=host,
                        port=port,
                        username=username,
                        password=password,
                        timeout=SSH_CONNECT_TIMEOUT,
                        banner_timeout=SSH_CONNECT_TIMEOUT,
                        auth_timeout=SSH_CONNECT_TIMEOUT
                    )
                    self._connections[server_id] = client
                    return client
                except Exception as e:
                    last_error = str(e)
                    if attempt < SSH_MAX_RETRIES - 1:
                        time.sleep(SSH_RETRY_DELAY * (attempt + 1))

            raise Exception(f'连接失败（重试{SSH_MAX_RETRIES}次）: {last_error}')

    def exec_command(self, server_id, command, timeout=SSH_COMMAND_TIMEOUT):
        """在远程服务器执行命令"""
        client = self.get_connection(server_id)
        # cd / 避免工作目录问题；注意：SSH shell 启动时可能产生
        # "Could not chdir to home directory" 警告（不影响命令执行）
        wrapped_cmd = f'cd / && {command}'
        try:
            stdin, stdout, stderr = client.exec_command(wrapped_cmd, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            stdout_data = stdout.read().decode('utf-8', errors='replace').strip()
            stderr_data = stderr.read().decode('utf-8', errors='replace').strip()
            return stdout_data, stderr_data, exit_code
        except Exception as e:
            # 连接可能已断开，尝试重新连接
            with self._get_lock(server_id):
                if server_id in self._connections:
                    try:
                        self._connections[server_id].close()
                    except:
                        pass
                    del self._connections[server_id]
            # 重试一次
            client = self.get_connection(server_id)
            stdin, stdout, stderr = client.exec_command(wrapped_cmd, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            stdout_data = stdout.read().decode('utf-8', errors='replace').strip()
            stderr_data = stderr.read().decode('utf-8', errors='replace').strip()
            return stdout_data, stderr_data, exit_code

    def upload_file(self, server_id, local_path, remote_path):
        """上传文件到远程服务器"""
        client = self.get_connection(server_id)
        sftp = client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
            return True
        finally:
            sftp.close()

    def download_file(self, server_id, remote_path, local_path):
        """从远程服务器下载文件"""
        client = self.get_connection(server_id)
        sftp = client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
            return True
        finally:
            sftp.close()

    def close_connection(self, server_id):
        """关闭指定服务器的连接"""
        with self._get_lock(server_id):
            if server_id in self._connections:
                try:
                    self._connections[server_id].close()
                except:
                    pass
                del self._connections[server_id]

    def close_all(self):
        """关闭所有连接"""
        for server_id in list(self._connections.keys()):
            self.close_connection(server_id)
