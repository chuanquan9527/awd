/**
 * 监控面板前端逻辑
 */

// ==================== 监控页面初始化 ====================
function initMonitorPage() {
    const filePanel = document.getElementById('monitor-file');
    const processPanel = document.getElementById('monitor-process');

    filePanel.innerHTML = `
        <div class="monitor-control">
            <div class="form-row">
                <div class="form-group">
                    <label>选择服务器</label>
                    <select id="monitorServerSelect" onchange="loadMonitorServer()">
                        <option value="">-- 请选择服务器 --</option>
                        ${AppState.servers.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.host)})</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>监控间隔(秒)</label>
                    <input type="number" id="monitorInterval" value="5" min="2" max="300">
                </div>
            </div>
            <div id="monitorServerControls" style="display:none;">
                <div style="display:flex;gap:0.75rem;margin-bottom:1rem;">
                    <button class="btn btn-success" id="buildBaselineBtn" onclick="doBuildBaseline()">建立基线</button>
                    <button class="btn btn-primary" id="startMonitorBtn" onclick="doStartMonitor('file')">启动文件监控</button>
                    <button class="btn btn-danger" id="stopMonitorBtn" onclick="doStopMonitor('file')">停止监控</button>
                </div>
                <div id="monitorStatusInfo"></div>
            </div>
        </div>
        <div class="monitor-alerts-section">
            <div class="section-header">
                <h3>告警记录</h3>
                <div style="display:flex;gap:0.5rem;">
                    <button class="btn btn-sm btn-secondary" onclick="loadAlerts()">刷新</button>
                    <button class="btn btn-sm btn-secondary" onclick="markAllAlertsRead()">全部已读</button>
                    <label class="toggle-switch" title="告警音效">
                        <input type="checkbox" checked onchange="toggleAlarm(this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            <div id="alertList"></div>
        </div>
    `;

    processPanel.innerHTML = `
        <div class="monitor-control">
            <div class="form-row">
                <div class="form-group">
                    <label>选择服务器</label>
                    <select id="processServerSelect" onchange="loadProcessList()">
                        <option value="">-- 请选择服务器 --</option>
                        ${AppState.servers.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.host)})</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>监控间隔(秒)</label>
                    <input type="number" id="processMonitorInterval" value="5" min="2" max="300">
                </div>
            </div>
            <div id="processServerControls" style="display:none;">
                <div style="display:flex;gap:0.75rem;margin-bottom:1rem;align-items:center;">
                    <button class="btn btn-primary" onclick="doStartMonitor('process')">启动进程监控</button>
                    <button class="btn btn-danger" onclick="doStopMonitor('process')">停止监控</button>
                    <label style="display:flex;align-items:center;gap:0.3rem;font-size:0.85rem;color:var(--text-secondary);">
                        <input type="checkbox" id="killOnDetect"> 检测到异常自动杀进程
                    </label>
                </div>
            </div>
        </div>
        <div id="processListContainer">
            <p class="placeholder-text">请先选择服务器</p>
        </div>
    `;
}

async function loadMonitorServer() {
    const serverId = document.getElementById('monitorServerSelect').value;
    const controls = document.getElementById('monitorServerControls');
    if (!serverId) { controls.style.display = 'none'; return; }
    controls.style.display = 'block';
    AppState.selectedServer = parseInt(serverId);
    loadMonitorStatus();
    loadAlerts();
}

async function loadProcessList() {
    const serverId = document.getElementById('processServerSelect').value;
    const controls = document.getElementById('processServerControls');
    const container = document.getElementById('processListContainer');

    if (!serverId) {
        controls.style.display = 'none';
        container.innerHTML = '<p class="placeholder-text">请先选择服务器</p>';
        return;
    }
    controls.style.display = 'block';

    container.innerHTML = '<p style="color:var(--text-muted);text-align:center;">加载中...</p>';

    const result = await apiRequest(`/api/servers/${serverId}/processes`);
    if (!result || !result.success) {
        container.innerHTML = '<p class="placeholder-text">获取进程列表失败</p>';
        return;
    }

    const processes = result.data || [];
    if (processes.length === 0) {
        container.innerHTML = '<p class="placeholder-text">无进程数据</p>';
        return;
    }

    container.innerHTML = `
        <div class="table-wrap" style="max-height:500px;">
            <table>
                <thead>
                    <tr>
                        <th>PID</th>
                        <th>用户</th>
                        <th>CPU%</th>
                        <th>MEM%</th>
                        <th>状态</th>
                        <th>命令</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${processes.map(p => `
                        <tr style="${p.suspicious ? 'background:rgba(239,68,68,0.1);' : ''}">
                            <td>${escapeHtml(p.pid)}</td>
                            <td>${escapeHtml(p.user)}</td>
                            <td>${p.cpu}</td>
                            <td>${p.mem}</td>
                            <td>${escapeHtml(p.stat)}</td>
                            <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(p.command)}">${escapeHtml(p.command)}</td>
                            <td>
                                ${p.suspicious ? '<span class="badge badge-critical">可疑</span>' : ''}
                                <button class="btn btn-sm btn-danger" onclick="doKillProcess(${serverId}, ${p.pid})">Kill</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function doBuildBaseline() {
    const serverId = AppState.selectedServer;
    if (!serverId) return;

    const btn = document.getElementById('buildBaselineBtn');
    btn.disabled = true;
    btn.textContent = '建立中...';

    const result = await apiRequest(`/api/servers/${serverId}/monitor/baseline`, { method: 'POST' });
    btn.disabled = false;
    btn.textContent = '建立基线';

    if (result && result.success) {
        alert(result.message);
        loadMonitorStatus();
    } else {
        alert(result ? result.message : '建立基线失败');
    }
}

async function doStartMonitor(type) {
    const serverId = AppState.selectedServer || parseInt(document.getElementById('processServerSelect').value);
    if (!serverId) { alert('请先选择服务器'); return; }

    const interval = parseInt(document.getElementById(type === 'file' ? 'monitorInterval' : 'processMonitorInterval').value) || 5;
    const killOnDetect = document.getElementById('killOnDetect')?.checked || false;

    const result = await apiRequest(`/api/servers/${serverId}/monitor/start`, {
        method: 'POST',
        body: { type, interval, kill_on_detect: killOnDetect }
    });

    if (result && result.success) {
        alert(result.message);
        loadMonitorStatus();
    } else {
        alert(result ? result.message : '启动失败');
    }
}

async function doStopMonitor(type) {
    const serverId = AppState.selectedServer || parseInt(document.getElementById('processServerSelect').value);
    if (!serverId) return;

    const result = await apiRequest(`/api/servers/${serverId}/monitor/stop`, {
        method: 'POST',
        body: { type }
    });

    if (result && result.success) {
        alert(result.message);
        loadMonitorStatus();
    }
}

async function loadMonitorStatus() {
    const serverId = AppState.selectedServer;
    if (!serverId) return;

    const result = await apiRequest(`/api/servers/${serverId}/monitor/status`);
    if (!result || !result.success) return;

    const d = result.data;
    const statusDiv = document.getElementById('monitorStatusInfo');
    if (statusDiv) {
        statusDiv.innerHTML = `
            <div style="display:flex;gap:1rem;font-size:0.85rem;">
                <span>文件监控: <span class="badge badge-${d.file_monitor_enabled ? 'online' : 'offline'}">${d.file_monitor_enabled ? '运行中' : '未启动'}</span></span>
                <span>进程监控: <span class="badge badge-${d.process_monitor_enabled ? 'online' : 'offline'}">${d.process_monitor_enabled ? '运行中' : '未启动'}</span></span>
                <span>流量监控: <span class="badge badge-${d.traffic_monitor_enabled ? 'online' : 'offline'}">${d.traffic_monitor_enabled ? '运行中' : '未启动'}</span></span>
                <span>间隔: ${d.monitor_interval}s</span>
            </div>
        `;
    }
}

async function loadAlerts() {
    const result = await apiRequest('/api/alerts?limit=50');
    if (!result || !result.success) return;

    AppState.unreadAlerts = result.unread_count || 0;
    updateAlertBadge();
    document.getElementById('statusAlerts').textContent = `未读告警: ${AppState.unreadAlerts}`;

    const container = document.getElementById('alertList');
    if (!container) return;

    const alerts = result.data || [];
    if (alerts.length === 0) {
        container.innerHTML = '<p class="placeholder-text">暂无告警记录</p>';
        return;
    }

    container.innerHTML = alerts.map(a => `
        <div class="alert-item ${a.severity} ${a.is_read ? '' : 'unread'}">
            <span class="alert-icon">${a.severity === 'critical' ? '🔴' : a.severity === 'warning' ? '🟡' : '🔵'}</span>
            <div class="alert-content">
                <div class="alert-title">${escapeHtml(a.message)}</div>
                <div class="alert-desc">${a.alert_type} | ${a.created_at}</div>
            </div>
        </div>
    `).join('');
}

async function doKillProcess(serverId, pid) {
    if (!confirm(`确定要终止进程 ${pid} 吗？`)) return;

    const result = await apiRequest(`/api/servers/${serverId}/processes/${pid}/kill`, { method: 'POST' });
    if (result && result.success) {
        alert(result.message);
        loadProcessList();
    } else {
        alert(result ? result.message : '操作失败');
    }
}

async function markAllAlertsRead() {
    await apiRequest('/api/alerts/read-all', { method: 'PUT' });
    AppState.unreadAlerts = 0;
    updateAlertBadge();
    document.getElementById('statusAlerts').textContent = '未读告警: 0';
    loadAlerts();
}

function toggleAlarm(enabled) {
    alarmEnabled = enabled;
}
