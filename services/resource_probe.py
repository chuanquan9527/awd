import ipaddress
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests as http_requests
from config import PROBE_DEFAULT_THREADS, PROBE_DEFAULT_TIMEOUT, PROBE_DEFAULT_PORTS


class ResourceProbe:
    """资源探测 - 批量检测 Web 服务可用性"""

    def __init__(self):
        self._results = []
        self._progress = {'current': 0, 'total': 0, 'found': 0}

    def probe_targets(self, targets_config, whitelist=None, ports=None):
        """
        探测目标
        :param targets_config: dict with keys 'ips', 'cidrs', 'domains'
        :param whitelist: list of IPs/domains to exclude
        :param ports: list of ports to probe
        """
        targets = []

        # 解析 IP 范围
        for ip_range in targets_config.get('ips', []):
            targets.extend(self._expand_ip_range(ip_range))

        # 解析 CIDR
        for cidr in targets_config.get('cidrs', []):
            targets.extend(self._expand_cidr(cidr))

        # 解析域名（直接添加）
        for domain in targets_config.get('domains', []):
            targets.append(domain)

        # 去重
        targets = list(set(targets))

        # 白名单过滤
        if whitelist:
            whitelist_set = set(whitelist)
            targets = [t for t in targets if t not in whitelist_set]

        ports = ports or PROBE_DEFAULT_PORTS
        self._progress = {'current': 0, 'total': len(targets) * len(ports), 'found': 0}
        self._results = []

        # 多线程探测
        probe_tasks = []
        for target in targets:
            for port in ports:
                probe_tasks.append((target, port))

        with ThreadPoolExecutor(max_workers=PROBE_DEFAULT_THREADS) as executor:
            futures = {
                executor.submit(self._check_http, target, port): (target, port)
                for target, port in probe_tasks
            }
            for future in as_completed(futures):
                target, port = futures[future]
                self._progress['current'] += 1
                try:
                    result = future.result()
                    if result and result.get('accessible'):
                        self._results.append(result)
                        self._progress['found'] += 1
                except:
                    pass

        return self._results

    def _expand_ip_range(self, ip_range):
        """展开 IP 范围，支持格式: 192.168.1.1-192.168.1.100 或 192.168.1.1-100"""
        ip_range = ip_range.strip()
        if '-' in ip_range:
            parts = ip_range.split('-')
            if len(parts) == 2:
                start_ip = parts[0].strip()
                end_part = parts[1].strip()

                # 判断是完整 IP 还是只有最后一段
                if '.' in end_part:
                    end_ip = end_part
                else:
                    prefix = '.'.join(start_ip.split('.')[:-1])
                    end_ip = f'{prefix}.{end_part}'

                try:
                    start = int(ipaddress.IPv4Address(start_ip))
                    end = int(ipaddress.IPv4Address(end_ip))
                    return [str(ipaddress.IPv4Address(ip)) for ip in range(start, end + 1)]
                except:
                    pass

        # 单个 IP
        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip_range):
            return [ip_range]

        return []

    def _expand_cidr(self, cidr):
        """展开 CIDR 网段"""
        try:
            network = ipaddress.IPv4Network(cidr, strict=False)
            return [str(ip) for ip in network.hosts()]
        except:
            return []

    def _check_http(self, target, port, timeout=PROBE_DEFAULT_TIMEOUT):
        """检测单个目标的 HTTP 可用性"""
        protocol = 'https' if port in [443, 8443] else 'http'
        url = f'{protocol}://{target}:{port}'

        try:
            resp = http_requests.get(
                url,
                timeout=timeout,
                verify=False,
                allow_redirects=False,
                headers={'User-Agent': 'AWD-Defense-Probe/1.0'}
            )

            # 提取页面标题
            title = ''
            content_type = resp.headers.get('Content-Type', '')
            if 'text/html' in content_type:
                title_match = re.search(r'<title>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = title_match.group(1).strip()[:100]

            return {
                'ip': target,
                'port': port,
                'url': url,
                'accessible': True,
                'status_code': resp.status_code,
                'title': title,
                'response_time': round(resp.elapsed.total_seconds(), 3),
                'content_type': content_type
            }
        except http_requests.exceptions.SSLError:
            # HTTPS 但证书无效，仍算可访问
            try:
                resp = http_requests.get(
                    url, timeout=timeout, verify=False, allow_redirects=False,
                    headers={'User-Agent': 'AWD-Defense-Probe/1.0'}
                )
                return {
                    'ip': target, 'port': port, 'url': url,
                    'accessible': True, 'status_code': resp.status_code,
                    'title': '', 'response_time': round(resp.elapsed.total_seconds(), 3),
                    'content_type': ''
                }
            except:
                return None
        except:
            return None

    def get_progress(self):
        """获取探测进度"""
        return self._progress

    def get_results(self):
        """获取探测结果"""
        return self._results
