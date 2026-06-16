/**
 * 资源探测前端逻辑
 */

let probePolling = null;

function initProbePage() {
    const content = document.getElementById('probeContent');
    content.innerHTML = `
        <div class="probe-form">
            <div class="form-row">
                <div class="form-group">
                    <label>探测目标（每行一个）</label>
                    <textarea id="probeTargets" rows="4" placeholder="支持格式：
IP范围: 192.168.1.1-192.168.1.100
CIDR: 192.168.1.0/24
域名: target1.com
单个IP: 10.0.0.5"></textarea>
                </div>
                <div class="form-group">
                    <label>白名单（排除，每行一个）</label>
                    <textarea id="probeWhitelist" rows="4" placeholder="如:
192.168.1.1
裁判机IP
本机IP"></textarea>
                </div>
            </div>
            <div style="display:flex;gap:0.75rem;align-items:center;">
                <button class="btn btn-primary" id="startProbeBtn" onclick="doStartProbe()">开始探测</button>
                <button class="btn btn-secondary" onclick="loadProbeResults()">刷新结果</button>
            </div>
        </div>
        <div id="probeProgress" style="margin-top:1rem;display:none;">
            <div style="display:flex;justify-content:space-between;font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.3rem;">
                <span id="probeProgressText">探测中...</span>
                <span id="probeProgressCount">0/0</span>
            </div>
            <div class="progress-bar">
                <div class="progress-bar-fill" id="probeProgressBar" style="width:0%"></div>
            </div>
        </div>
        <div class="probe-results" id="probeResults" style="margin-top:1rem;"></div>
    `;
}

async function doStartProbe() {
    const targets = document.getElementById('probeTargets').value.trim();
    if (!targets) { alert('请输入探测目标'); return; }

    const whitelist = document.getElementById('probeWhitelist').value.trim();
    const btn = document.getElementById('startProbeBtn');
    btn.disabled = true;
    btn.textContent = '探测中...';

    const result = await apiRequest('/api/probe', {
        method: 'POST',
        body: { targets, whitelist }
    });

    if (result && result.success) {
        document.getElementById('probeProgress').style.display = 'block';
        // 开始轮询结果
        if (probePolling) clearInterval(probePolling);
        probePolling = setInterval(loadProbeResults, 2000);
    } else {
        alert(result ? result.message : '启动探测失败');
        btn.disabled = false;
        btn.textContent = '开始探测';
    }
}

async function loadProbeResults() {
    const result = await apiRequest('/api/probe/results');
    if (!result || !result.success) return;

    const data = result.data;
    const progress = data.progress;
    const results = data.results || [];

    // 更新进度
    if (progress.total > 0) {
        const pct = Math.round((progress.current / progress.total) * 100);
        document.getElementById('probeProgressBar').style.width = pct + '%';
        document.getElementById('probeProgressCount').textContent = `${progress.current}/${progress.total} (发现 ${progress.found})`;

        if (progress.current >= progress.total) {
            document.getElementById('probeProgressText').textContent = '探测完成';
            if (probePolling) { clearInterval(probePolling); probePolling = null; }
            const btn = document.getElementById('startProbeBtn');
            btn.disabled = false;
            btn.textContent = '开始探测';
        }
    }

    // 渲染结果
    const container = document.getElementById('probeResults');
    if (results.length === 0) {
        container.innerHTML = '<p class="placeholder-text">暂无探测结果</p>';
        return;
    }

    container.innerHTML = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>IP</th>
                        <th>端口</th>
                        <th>状态码</th>
                        <th>标题</th>
                        <th>响应时间</th>
                        <th>URL</th>
                    </tr>
                </thead>
                <tbody>
                    ${results.map(r => `
                        <tr>
                            <td><span class="badge badge-online">${escapeHtml(r.ip)}</span></td>
                            <td>${r.port}</td>
                            <td><span class="badge badge-${r.status_code < 400 ? 'info' : 'critical'}">${r.status_code}</span></td>
                            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(r.title || '-')}</td>
                            <td>${r.response_time}s</td>
                            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                                <a href="${escapeHtml(r.url)}" target="_blank" style="color:var(--accent-blue);">${escapeHtml(r.url)}</a>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}
