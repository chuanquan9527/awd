/**
 * 监控面板前端逻辑
 */

// ==================== 监控页面初始化 ====================
function initMonitorPage() {
    const filePanel = document.getElementById('monitor-file');
    const processPanel = document.getElementById('monitor-process');

    // 注意：restoreAlarmState() 必须在 HTML 生成之后调用，因为需要访问 DOM 元素

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
            <div id="watchedDirsRow" style="display:none;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem;">
                    <label style="font-size:0.85rem;color:var(--text-secondary);">监控目录列表</label>
                    <button class="btn btn-sm btn-success" onclick="addWatchedDirItem()" title="新增目录">➕ 新增</button>
                </div>
                <div class="table-wrap" style="max-height:300px;">
                    <table id="watchedDirsTable" class="watched-dirs-table">
                        <thead>
                            <tr>
                                <th style="width:35%;">目录</th>
                                <th style="width:55%;">白名单（正则匹配）</th>
                                <th style="width:10%;">操作</th>
                            </tr>
                        </thead>
                        <tbody id="watchedDirsContainer">
                            <!-- 目录列表将通过JS动态生成 -->
                        </tbody>
                    </table>
                </div>
            </div>
            <div id="monitorServerControls" style="display:none;">
                <div style="display:flex;gap:0.75rem;margin-bottom:1rem;align-items:center;">
                    <button class="btn btn-success" id="buildBaselineBtn" onclick="doBuildBaseline()">建立基线</button>
                    <label class="toggle-switch" title="文件监控开关" style="margin-left:0.5rem;">
                        <input type="checkbox" id="fileMonitorSwitch" onchange="toggleFileMonitor(this.checked)">
                        <span class="toggle-slider"></span>
                        <span style="margin-left:0.5rem;font-size:0.85rem;">文件监控</span>
                    </label>
                    <label class="toggle-switch" title="告警音效开关">
                        <input type="checkbox" id="alarmSoundSwitch" onchange="toggleAlarm(this.checked)">
                        <span class="toggle-slider"></span>
                        <span style="margin-left:0.5rem;font-size:0.85rem;">告警音效</span>
                    </label>
                </div>
                <div id="monitorStatusInfo"></div>
            </div>
        </div>
        <div class="monitor-alerts-section">
            <div class="section-header">
                <h3>告警记录</h3>
                <div style="display:flex;gap:0.5rem;align-items:center;">
                    <button class="btn btn-sm btn-secondary" onclick="loadAlerts()">刷新</button>
                    <button class="btn btn-sm btn-secondary" onclick="markAllAlertsRead()">全部已读</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteAllAlerts()">全部删除</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteSelectedAlerts()" id="deleteSelectedBtn" style="display:none;">删除选中</button>
                </div>
            </div>
            <div id="alertList"></div>
        </div>
    `;

    // HTML 生成后恢复音效开关状态
    restoreAlarmState();

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
    const dirsRow = document.getElementById('watchedDirsRow');
    
    if (!serverId) { 
        controls.style.display = 'none'; 
        dirsRow.style.display = 'none';
        return; 
    }
    
    controls.style.display = 'block';
    dirsRow.style.display = 'block';
    AppState.selectedServer = parseInt(serverId);
    
    // 从服务器信息获取 web_root 作为默认值
    const server = AppState.servers.find(s => s.id === AppState.selectedServer);
    
    // 加载已保存的监控配置（目录和白名单）
    const configResult = await apiRequest(`/api/servers/${serverId}/monitor/status`);
    if (configResult && configResult.success && configResult.data) {
        const config = configResult.data;
        let dirConfigs = [{dir: '/var/www/html', whitelist: ''}];
        
        // 解析已保存的监控配置（新格式：[{dir, whitelist}]）
        if (config.watched_dirs) {
            try {
                const savedConfig = JSON.parse(config.watched_dirs);
                if (savedConfig && savedConfig.length > 0) {
                    // 检查是否是新格式（对象数组）还是旧格式（字符串数组）
                    if (typeof savedConfig[0] === 'object') {
                        dirConfigs = savedConfig;
                    } else {
                        // 旧格式转换为新格式
                        dirConfigs = savedConfig.map(d => ({dir: d, whitelist: ''}));
                        // 如果有全局白名单，应用到第一个目录
                        if (config.whitelist) {
                            dirConfigs[0].whitelist = config.whitelist;
                        }
                    }
                }
            } catch (e) {
                console.error('[监控] 解析监控配置失败:', e);
            }
        }
        
        // 如果没有保存的目录，使用服务器默认 web_root
        if (dirConfigs.length === 0 && server && server.web_root) {
            dirConfigs = [{dir: server.web_root, whitelist: ''}];
        }
        
        // 初始化目录列表
        initWatchedDirsList(dirConfigs);
    } else if (server && server.web_root) {
        // 没有保存的配置，使用服务器默认值
        initWatchedDirsList([{dir: server.web_root, whitelist: ''}]);
    }
    
    loadMonitorStatus();
    loadAlerts();
}

// ==================== 监控目录列表管理 ====================

// 初始化监控目录列表（每行包含目录和白名单）
function initWatchedDirsList(dirConfigs = [{dir: '/var/www/html', whitelist: ''}]) {
    const container = document.getElementById('watchedDirsContainer');
    
    // 确保至少有一个目录
    if (dirConfigs.length === 0) {
        dirConfigs = [{dir: '/var/www/html', whitelist: ''}];
    }
    
    container.innerHTML = dirConfigs.map((config, index) => `
        <tr class="watched-dir-row" data-index="${index}">
            <td>
                <input type="text" class="watched-dir-input" value="${escapeHtml(config.dir)}" placeholder="/var/www/html">
            </td>
            <td>
                <textarea class="whitelist-input" placeholder="每行一个正则表达式，例如：&#10;.*\\.log&#10;.*\\.git.*">${escapeHtml(config.whitelist || '')}</textarea>
            </td>
            <td class="action-cell">
                ${dirConfigs.length > 1 ? `<button class="btn btn-sm btn-danger" onclick="removeWatchedDirItem(${index})" title="移除">移除</button>` : ''}
            </td>
        </tr>
    `).join('');
}

// 新增监控目录
function addWatchedDirItem() {
    const container = document.getElementById('watchedDirsContainer');
    const rows = container.querySelectorAll('.watched-dir-row');
    const newIndex = rows.length;
    
    // 创建新的目录行
    const newRow = document.createElement('tr');
    newRow.className = 'watched-dir-row';
    newRow.dataset.index = newIndex;
    newRow.innerHTML = `
        <td>
            <input type="text" class="watched-dir-input" value="" placeholder="/var/www/html">
        </td>
        <td>
            <textarea class="whitelist-input" placeholder="每行一个正则表达式，例如：&#10;.*\\.log&#10;.*\\.git.*"></textarea>
        </td>
        <td class="action-cell">
            <button class="btn btn-sm btn-danger" onclick="removeWatchedDirItem(${newIndex})" title="移除">移除</button>
        </td>
    `;
    
    container.appendChild(newRow);
    
    // 重新索引并更新按钮状态
    reindexWatchedDirsList();
}

// 移除监控目录
function removeWatchedDirItem(index) {
    const container = document.getElementById('watchedDirsContainer');
    const rows = container.querySelectorAll('.watched-dir-row');
    
    // 确保至少保留一个目录
    if (rows.length <= 1) {
        alert('必须保留至少一个监控目录');
        return;
    }
    
    const row = container.querySelector(`.watched-dir-row[data-index="${index}"]`);
    if (row) {
        row.remove();
    }
    
    // 重新索引
    reindexWatchedDirsList();
}

// 重新索引目录列表
function reindexWatchedDirsList() {
    const container = document.getElementById('watchedDirsContainer');
    const rows = container.querySelectorAll('.watched-dir-row');
    
    rows.forEach((row, i) => {
        row.dataset.index = i;
        
        // 更新移除按钮
        const actionCell = row.querySelector('.action-cell');
        if (rows.length > 1) {
            if (!actionCell.querySelector('button')) {
                actionCell.innerHTML = `<button class="btn btn-sm btn-danger" onclick="removeWatchedDirItem(${i})" title="移除">移除</button>`;
            } else {
                actionCell.querySelector('button').onclick = () => removeWatchedDirItem(i);
            }
        } else {
            // 只剩一个时隐藏移除按钮
            actionCell.innerHTML = '';
        }
    });
}

// 获取所有监控配置（目录和白名单）
function getWatchedDirConfigs() {
    const rows = document.querySelectorAll('.watched-dir-row');
    const configs = [];
    rows.forEach(row => {
        const dirInput = row.querySelector('.watched-dir-input');
        const whitelistInput = row.querySelector('.whitelist-input');
        const dir = dirInput ? dirInput.value.trim() : '';
        const whitelist = whitelistInput ? whitelistInput.value.trim() : '';
        if (dir) {
            configs.push({dir, whitelist});
        }
    });
    // 确保至少返回一个目录
    return configs.length > 0 ? configs : [{dir: '/var/www/html', whitelist: ''}];
}

// 获取所有监控目录（兼容旧接口）
function getWatchedDirs() {
    const configs = getWatchedDirConfigs();
    return configs.map(c => c.dir);
}

// 获取白名单（兼容旧接口，返回第一个目录的白名单）
function getWhitelist() {
    const configs = getWatchedDirConfigs();
    return configs.length > 0 ? configs[0].whitelist : '';
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

    // 检查文件监控状态
    const statusResult = await apiRequest(`/api/servers/${serverId}/monitor/status`);
    if (statusResult && statusResult.data && statusResult.data.file_monitor_enabled) {
        // 文件监控正在运行，提示用户先停止监控
        const confirmStop = confirm('文件监控正在运行中，重建基线需要先停止监控。\n\n是否停止监控并继续重建基线？');
        if (!confirmStop) {
            console.log('[基线] 用户取消重建基线操作');
            return;
        }
        
        // 停止文件监控
        console.log('[基线] 先停止文件监控...');
        const stopResult = await apiRequest(`/api/servers/${serverId}/monitor/stop`, {
            method: 'POST',
            body: { type: 'file' }
        });
        
        if (!stopResult || !stopResult.success) {
            alert('停止监控失败，无法重建基线');
            return;
        }
        
        // 更新开关状态
        const fileMonitorSwitch = document.getElementById('fileMonitorSwitch');
        if (fileMonitorSwitch) {
            fileMonitorSwitch.checked = false;
        }
        stopAlertRefreshTimer();
        console.log('[基线] 文件监控已停止，继续重建基线');
    }

    // 获取用户输入的监控配置（目录和白名单）
    const dirConfigs = getWatchedDirConfigs();
    if (dirConfigs.length === 0 || !dirConfigs.some(c => c.dir)) {
        alert('请输入至少一个监控目录');
        return;
    }

    const btn = document.getElementById('buildBaselineBtn');
    btn.disabled = true;
    btn.textContent = '建立中...';

    const result = await apiRequest(`/api/servers/${serverId}/monitor/baseline`, {
        method: 'POST',
        body: { dir_configs: dirConfigs }
    });
    btn.disabled = false;
    btn.textContent = '建立基线';

    if (result && result.success) {
        alert(result.message);
        loadMonitorStatus();
    } else {
        alert(result ? result.message : '建立基线失败');
    }
}

async function doStartMonitor(type, silent = false) {
    const serverId = AppState.selectedServer || parseInt(document.getElementById('processServerSelect').value);
    if (!serverId) { 
        if (!silent) alert('请先选择服务器'); 
        return; 
    }

    const interval = parseInt(document.getElementById(type === 'file' ? 'monitorInterval' : 'processMonitorInterval').value) || 5;
    const killOnDetect = document.getElementById('killOnDetect')?.checked || false;
    
    // 文件监控时获取监控配置（目录和白名单）
    let dirConfigs = null;
    if (type === 'file') {
        dirConfigs = getWatchedDirConfigs();
        if (dirConfigs.length === 0 || !dirConfigs.some(c => c.dir)) {
            if (!silent) alert('请输入至少一个监控目录');
            return;
        }
    }

    const result = await apiRequest(`/api/servers/${serverId}/monitor/start`, {
        method: 'POST',
        body: { type, interval, kill_on_detect: killOnDetect, dir_configs: dirConfigs }
    });

    if (result && result.success) {
        if (!silent) console.log('[监控]', result.message);
        loadMonitorStatus();
        
        // 启动文件监控后，定时刷新告警列表
        if (type === 'file') {
            startAlertRefreshTimer(interval);
        }
    } else {
        if (!silent) alert(result ? result.message : '启动失败');
        // 启动失败时，恢复开关状态
        const switchEl = document.getElementById('fileMonitorSwitch');
        if (switchEl) switchEl.checked = false;
    }
}

async function doStopMonitor(type, silent = false) {
    const serverId = AppState.selectedServer || parseInt(document.getElementById('processServerSelect').value);
    if (!serverId) return;

    const result = await apiRequest(`/api/servers/${serverId}/monitor/stop`, {
        method: 'POST',
        body: { type }
    });

    if (result && result.success) {
        if (!silent) console.log('[监控]', result.message);
        loadMonitorStatus();
        
        // 停止文件监控后，关闭定时刷新
        if (type === 'file') {
            stopAlertRefreshTimer();
        }
    } else {
        if (!silent) alert(result ? result.message : '停止失败');
        // 停止失败时，恢复开关状态
        const switchEl = document.getElementById('fileMonitorSwitch');
        if (switchEl) switchEl.checked = true;
    }
}

// ==================== 告警定时刷新 ====================
let alertRefreshTimer = null;

function toggleFileMonitor(enabled) {
    if (enabled) {
        doStartMonitor('file', true);
    } else {
        doStopMonitor('file', true);
    }
}

function startAlertRefreshTimer(interval) {
    // 先清除旧的定时器
    stopAlertRefreshTimer();
    
    // 设置新的定时器，每隔interval秒刷新告警列表
    alertRefreshTimer = setInterval(() => {
        loadAlerts();
    }, interval * 1000);
    
    console.log(`[文件监控] 告警定时刷新已启动，间隔 ${interval} 秒`);
}

function stopAlertRefreshTimer() {
    if (alertRefreshTimer) {
        clearInterval(alertRefreshTimer);
        alertRefreshTimer = null;
        console.log('[文件监控] 告警定时刷新已停止');
    }
}

async function loadMonitorStatus() {
    const serverId = AppState.selectedServer;
    if (!serverId) return;

    const result = await apiRequest(`/api/servers/${serverId}/monitor/status`);
    if (!result || !result.success) return;

    const d = result.data;
    
    // 更新基线按钮文本
    const baselineBtn = document.getElementById('buildBaselineBtn');
    if (baselineBtn) {
        baselineBtn.textContent = d.has_baseline ? '重建基线' : '建立基线';
        baselineBtn.className = d.has_baseline ? 'btn btn-warning' : 'btn btn-success';
    }
    
    // 更新文件监控开关状态
    const fileMonitorSwitch = document.getElementById('fileMonitorSwitch');
    if (fileMonitorSwitch) {
        fileMonitorSwitch.checked = d.file_monitor_enabled;
        // 根据监控状态启动/停止定时刷新
        if (d.file_monitor_enabled) {
            startAlertRefreshTimer(d.monitor_interval || 5);
        } else {
            stopAlertRefreshTimer();
        }
    }
    
    // 更新音效开关状态（从localStorage恢复）
    const alarmSoundSwitch = document.getElementById('alarmSoundSwitch');
    if (alarmSoundSwitch) {
        const savedState = localStorage.getItem('alarmEnabled');
        alarmSoundSwitch.checked = savedState !== 'false'; // 默认true
        window.alarmEnabled = alarmSoundSwitch.checked;
    }
    
    // 更新状态信息
    const statusDiv = document.getElementById('monitorStatusInfo');
    if (statusDiv) {
        statusDiv.innerHTML = `
            <div style="display:flex;gap:1rem;font-size:0.85rem;">
                <span>文件监控: <span class="badge badge-${d.file_monitor_enabled ? 'online' : 'offline'}">${d.file_monitor_enabled ? '运行中' : '未启动'}</span></span>
                <span>进程监控: <span class="badge badge-${d.process_monitor_enabled ? 'online' : 'offline'}">${d.process_monitor_enabled ? '运行中' : '未启动'}</span></span>
                <span>流量监控: <span class="badge badge-${d.traffic_monitor_enabled ? 'online' : 'offline'}">${d.traffic_monitor_enabled ? '运行中' : '未启动'}</span></span>
                <span>间隔: ${d.monitor_interval}s</span>
                <span>基线: <span class="badge badge-${d.has_baseline ? 'online' : 'offline'}">${d.has_baseline ? '已建立' : '未建立'}</span></span>
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
        updateDeleteSelectedBtn();
        return;
    }

    container.innerHTML = `
        <div class="alert-list-header" style="display:flex;gap:0.5rem;padding:0.5rem 0;border-bottom:1px solid var(--border-color);">
            <input type="checkbox" id="selectAllAlerts" onchange="toggleSelectAllAlerts(this.checked)" style="margin-right:0.5rem;">
            <span style="font-size:0.85rem;color:var(--text-muted);">全选</span>
        </div>
        ${alerts.map(a => `
            <div class="alert-item ${a.severity} ${a.is_read ? '' : 'unread'}" data-id="${a.id}">
                <input type="checkbox" class="alert-checkbox" data-id="${a.id}" onchange="updateDeleteSelectedBtn()" style="margin-right:0.5rem;">
                <span class="alert-icon">${a.severity === 'critical' ? '🔴' : a.severity === 'warning' ? '🟡' : '🔵'}</span>
                <div class="alert-content">
                    <div class="alert-title">${escapeHtml(a.message)}</div>
                    <div class="alert-desc">${a.alert_type} | ${a.created_at}</div>
                </div>
                <button class="btn btn-sm btn-danger" onclick="deleteAlert(${a.id})" title="删除" style="margin-left:auto;padding:0.2rem 0.5rem;font-size:0.75rem;">删除</button>
            </div>
        `).join('')}
    `;
    updateDeleteSelectedBtn();
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

// ==================== 告警删除功能 ====================

function toggleSelectAllAlerts(checked) {
    const checkboxes = document.querySelectorAll('.alert-checkbox');
    checkboxes.forEach(cb => cb.checked = checked);
    updateDeleteSelectedBtn();
}

function updateDeleteSelectedBtn() {
    const checkboxes = document.querySelectorAll('.alert-checkbox:checked');
    const btn = document.getElementById('deleteSelectedBtn');
    if (btn) {
        btn.style.display = checkboxes.length > 0 ? 'inline-block' : 'none';
        btn.textContent = checkboxes.length > 0 ? `删除选中(${checkboxes.length})` : '删除选中';
    }
}

async function deleteAlert(alertId) {
    if (!confirm('确定要删除这条告警吗？')) return;
    
    const result = await apiRequest(`/api/alerts/${alertId}`, { method: 'DELETE' });
    if (result && result.success) {
        loadAlerts();
    } else {
        alert(result ? result.message : '删除失败');
    }
}

async function deleteSelectedAlerts() {
    const checkboxes = document.querySelectorAll('.alert-checkbox:checked');
    if (checkboxes.length === 0) {
        alert('请先选择要删除的告警');
        return;
    }
    
    const ids = Array.from(checkboxes).map(cb => parseInt(cb.dataset.id));
    if (!confirm(`确定要删除选中的 ${ids.length} 条告警吗？`)) return;
    
    const result = await apiRequest('/api/alerts/batch', {
        method: 'DELETE',
        body: { ids }
    });
    
    if (result && result.success) {
        loadAlerts();
    } else {
        alert(result ? result.message : '删除失败');
    }
}

async function deleteAllAlerts() {
    if (!confirm('确定要删除所有告警记录吗？此操作不可恢复！')) return;
    
    const result = await apiRequest('/api/alerts/all', { method: 'DELETE' });
    if (result && result.success) {
        AppState.unreadAlerts = 0;
        updateAlertBadge();
        document.getElementById('statusAlerts').textContent = '未读告警: 0';
        loadAlerts();
    } else {
        alert(result ? result.message : '删除失败');
    }
}

function toggleAlarm(enabled) {
    window.alarmEnabled = enabled;
    localStorage.setItem('alarmEnabled', enabled.toString());
    console.log('[监控] 告警音效开关:', enabled, '(已保存到localStorage)');
}

// 页面加载时恢复音效开关状态
function restoreAlarmState() {
    const savedState = localStorage.getItem('alarmEnabled');
    // 默认为 true（如果 localStorage 中没有保存值）
    window.alarmEnabled = savedState === null ? true : savedState === 'true';
    console.log('[监控] 从localStorage恢复音效状态:', window.alarmEnabled, 'savedState:', savedState);
    
    // 更新UI中的告警音效开关状态（使用正确的 ID）
    const alarmSoundSwitch = document.getElementById('alarmSoundSwitch');
    if (alarmSoundSwitch) {
        alarmSoundSwitch.checked = window.alarmEnabled;
        console.log('[监控] 告警音效开关UI已更新:', alarmSoundSwitch.checked);
    } else {
        console.log('[监控] 告警音效开关元素未找到');
    }
}
