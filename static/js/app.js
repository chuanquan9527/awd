/**
 * AWD 防御运维工作台 - 前端主逻辑
 */

// ==================== 全局状态 ====================
const AppState = {
    currentTab: 'servers',
    currentMonitorTab: 'file',
    servers: [],
    selectedServer: null,
    controlServerId: null,
    alerts: [],
    unreadAlerts: 0,
    user: null,
    isLoggedIn: false
};

// ==================== API 请求封装 ====================
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    };

    if (options.body && typeof options.body === 'object') {
        defaultOptions.body = JSON.stringify(options.body);
    }

    try {
        const response = await fetch(url, defaultOptions);
        if (response.status === 401) {
            // 未登录，跳转到登录页
            window.location.href = '/login';
            return null;
        }
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API请求失败:', error);
        return { success: false, message: '网络请求失败' };
    }
}

// ==================== 登录状态检查 ====================
async function checkAuth() {
    const data = await apiRequest('/api/auth/check');
    if (data && data.logged_in) {
        AppState.isLoggedIn = true;
        AppState.user = data.username;
        document.getElementById('userInfo').textContent = data.username;
        return true;
    }
    window.location.href = '/login';
    return false;
}

// ==================== 退出登录 ====================
async function logout() {
    await apiRequest('/api/auth/logout', { method: 'POST' });
    window.location.href = '/login';
}

// ==================== 修改密码 ====================
function showChangePasswordModal() {
    showModal('修改密码', `
        <div class="form-group">
            <label>旧密码</label>
            <input type="password" id="oldPassword" placeholder="请输入旧密码">
        </div>
        <div class="form-group">
            <label>新密码</label>
            <input type="password" id="newPassword" placeholder="新密码至少12位，包含大小写字母、数字和特殊字符">
        </div>
        <div class="form-group">
            <label>确认新密码</label>
            <input type="password" id="confirmPassword" placeholder="请再次输入新密码">
        </div>
        <div id="passwordError" style="color: var(--accent-red); font-size: 0.85rem; display: none;"></div>
    `, [
        { text: '取消', class: 'btn-secondary', action: hideModal },
        {
            text: '确认修改',
            class: 'btn-primary',
            action: async () => {
                const oldPassword = document.getElementById('oldPassword').value;
                const newPassword = document.getElementById('newPassword').value;
                const confirmPassword = document.getElementById('confirmPassword').value;
                const errorDiv = document.getElementById('passwordError');

                if (!oldPassword || !newPassword || !confirmPassword) {
                    errorDiv.textContent = '请填写所有字段';
                    errorDiv.style.display = 'block';
                    return;
                }

                if (newPassword !== confirmPassword) {
                    errorDiv.textContent = '两次输入的新密码不一致';
                    errorDiv.style.display = 'block';
                    return;
                }

                const result = await apiRequest('/api/auth/password', {
                    method: 'PUT',
                    body: { old_password: oldPassword, new_password: newPassword }
                });

                if (result && result.success) {
                    hideModal();
                    alert('密码修改成功，请重新登录');
                    logout();
                } else {
                    errorDiv.textContent = result ? result.message : '修改失败';
                    errorDiv.style.display = 'block';
                }
            }
        }
    ]);
}

// ==================== 标签页切换 ====================
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });

    // 监控子标签页
    document.querySelectorAll('.monitor-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const monitorTab = btn.dataset.monitor;
            switchMonitorTab(monitorTab);
        });
    });
}

function switchTab(tab) {
    AppState.currentTab = tab;

    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // 更新面板显示
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `panel-${tab}`);
    });

    // 触发标签页加载
    if (tab === 'servers') loadServers();
    if (tab === 'backup') initBackupPage();
    if (tab === 'waf') initWAFPage();
    if (tab === 'scripts') initScriptsPage();
    if (tab === 'monitor') { initMonitorPage(); loadMonitorData(); }
}

function switchMonitorTab(monitorTab) {
    AppState.currentMonitorTab = monitorTab;

    document.querySelectorAll('.monitor-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.monitor === monitorTab);
    });

    document.querySelectorAll('.monitor-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `monitor-${monitorTab}`);
    });
}

// ==================== 模态框 ====================
function showModal(title, bodyHtml, buttons = []) {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = bodyHtml;

    const footer = document.getElementById('modalFooter');
    footer.innerHTML = '';
    buttons.forEach(btn => {
        const button = document.createElement('button');
        button.className = `btn ${btn.class}`;
        button.textContent = btn.text;
        button.onclick = btn.action;
        footer.appendChild(button);
    });

    document.getElementById('modalOverlay').classList.add('show');
}

function hideModal() {
    document.getElementById('modalOverlay').classList.remove('show');
}

// ==================== 服务器管理 ====================
async function loadServers() {
    const data = await apiRequest('/api/servers');
    if (!data || !data.success) return;

    AppState.servers = data.data || [];
    ensureControlServer();
    renderServerList();
    updateStatusBar();
}

function renderServerList() {
    const container = document.getElementById('serverList');
    if (AppState.servers.length === 0) {
        container.innerHTML = '<p class="placeholder-text">暂无服务器，请点击右上角"新增服务器"添加</p>';
        return;
    }

    container.innerHTML = AppState.servers.map(server => {
        const webRootBadge = getWebRootBadge(server.web_root_status);
        const mysqlBadge = getMysqlBadge(server.mysql_conn_status);
        const typeIcon = server.server_type === 'own' ? '己' : '夺';
        const typeTitle = server.server_type === 'own' ? '己方主机' : '夺取主机';
        const statusIcon = server.status === 'online' ? '●' : '○';
        const statusTitle = server.status === 'online' ? '在线' : '离线';
        return `
        <div class="server-card ${server.server_type}" data-id="${server.id}">
            <div class="server-card-header">
                <div class="server-card-title">
                    <span class="status-dot ${server.status}"></span>
                    <h3>${escapeHtml(server.name)}</h3>
                    <span class="server-type-icon ${server.server_type}" title="${typeTitle}">${typeIcon}</span>
                    <span class="server-status-icon ${server.status}" title="${statusTitle}">${statusIcon}</span>
                </div>
                <div class="server-card-actions">
                    <button onclick="connectServer(${server.id})" title="连接">连接</button>
                    <button onclick="showEditServerModal(${server.id})" title="编辑">编辑</button>
                    <button onclick="showServerDetail(${server.id})" title="详情">详情</button>
                    <button onclick="deleteServer(${server.id})" title="删除">删除</button>
                </div>
            </div>
            <div class="server-info-grid">
                <div class="server-info-item">
                    <span class="label">IP:</span>
                    <span class="value">${escapeHtml(server.host)}:${server.port}</span>
                </div>
                <div class="server-info-item">
                    <span class="label">用户:</span>
                    <span class="value">${escapeHtml(server.username)}</span>
                </div>
                <div class="server-info-item">
                    <span class="label">内核:</span>
                    <span class="value">${escapeHtml(server.kernel_version || '未采集')}</span>
                </div>
                <div class="server-info-item">
                    <span class="label">PHP:</span>
                    <span class="value">${escapeHtml(server.php_version || '未采集')}</span>
                </div>
                <div class="server-info-item">
                    <span class="label">MySQL:</span>
                    <span class="value">${escapeHtml(server.mysql_version || '未采集')}</span>
                </div>
                <div class="server-info-item">
                    <span class="label">Web根目录:</span>
                    <span class="value">${escapeHtml(server.web_root)}</span>
                </div>
            </div>
            <div class="server-status-badges">
                ${webRootBadge}
                ${mysqlBadge}
            </div>
        </div>
    `}).join('');
}

function getWebRootBadge(status) {
    const map = {
        'available': { text: 'Web目录正常', cls: 'badge-online' },
        'readonly': { text: 'Web目录只读', cls: 'badge-warning' },
        'unavailable': { text: 'Web目录异常', cls: 'badge-offline' },
        'unknown': { text: 'Web目录未检测', cls: 'badge-info' }
    };
    const cfg = map[status] || map['unknown'];
    return `<span class="badge ${cfg.cls}">${cfg.text}</span>`;
}

function getMysqlBadge(status) {
    const map = {
        'available': { text: 'MySQL正常', cls: 'badge-online' },
        'unavailable': { text: 'MySQL异常', cls: 'badge-offline' },
        'not_configured': { text: 'MySQL未配置', cls: 'badge-info' },
        'unknown': { text: 'MySQL未检测', cls: 'badge-info' }
    };
    const cfg = map[status] || map['unknown'];
    return `<span class="badge ${cfg.cls}">${cfg.text}</span>`;
}

// ==================== 服务器弹窗表单（分类展示） ====================
function getServerFormHtml(server) {
    const s = server || {};
    const isEdit = !!server;
    return `
        <!-- 服务器基本信息 -->
        <div class="modal-section">
            <div class="modal-section-title">服务器基本信息</div>
            <div class="form-row">
                <div class="form-group">
                    <label>服务器名称 *</label>
                    <input type="text" id="serverName" placeholder="如: 靶机1" value="${escapeHtml(s.name || '')}">
                </div>
                <div class="form-group">
                    <label>服务器类型</label>
                    <select id="serverType">
                        <option value="own" ${s.server_type === 'own' ? 'selected' : ''}>己方主机</option>
                        <option value="captured" ${s.server_type === 'captured' ? 'selected' : ''}>夺取主机</option>
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>IP 地址 *</label>
                    <input type="text" id="serverHost" placeholder="如: 192.168.1.100" value="${escapeHtml(s.host || '')}">
                </div>
                <div class="form-group">
                    <label>SSH 端口</label>
                    <input type="number" id="serverPort" value="${s.port || 22}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>SSH 用户名 *</label>
                    <input type="text" id="serverUsername" value="${escapeHtml(s.username || 'root')}">
                </div>
                <div class="form-group">
                    <label>SSH 密码 ${isEdit ? '(留空表示不修改)' : '*'}</label>
                    <input type="password" id="serverPassword" placeholder="${isEdit ? '留空表示不修改' : 'SSH密码'}">
                </div>
            </div>
        </div>

        <!-- 网站信息 -->
        <div class="modal-section">
            <div class="modal-section-title">网站信息</div>
            <div class="form-group">
                <label>Web 根目录</label>
                <input type="text" id="serverWebRoot" value="${escapeHtml(s.web_root || '/var/www/html')}">
            </div>
        </div>

        <!-- 数据库信息 -->
        <div class="modal-section">
            <div class="modal-section-title">数据库信息</div>
            <div class="form-row">
                <div class="form-group">
                    <label>数据库名</label>
                    <input type="text" id="serverDbName" placeholder="留空表示全部数据库" value="${escapeHtml(s.db_name || '')}">
                </div>
                <div class="form-group">
                    <label>数据库用户</label>
                    <input type="text" id="serverDbUser" value="${escapeHtml(s.db_user || 'root')}">
                </div>
                <div class="form-group">
                    <label>数据库密码</label>
                    <input type="password" id="serverDbPassword" placeholder="数据库密码" value="${escapeHtml(s.db_password || '')}">
                </div>
            </div>
        </div>

        <div id="serverError" style="color: var(--accent-red); font-size: 0.85rem; display: none;"></div>
    `;
}

function getServerFormData(isEdit) {
    const data = {
        name: document.getElementById('serverName').value.trim(),
        server_type: document.getElementById('serverType').value,
        host: document.getElementById('serverHost').value.trim(),
        port: parseInt(document.getElementById('serverPort').value) || 22,
        username: document.getElementById('serverUsername').value.trim(),
        web_root: document.getElementById('serverWebRoot').value.trim(),
        db_name: document.getElementById('serverDbName').value.trim(),
        db_user: document.getElementById('serverDbUser').value.trim(),
        db_password: document.getElementById('serverDbPassword').value
    };
    const password = document.getElementById('serverPassword').value;
    if (password) {
        data.password = password;
    }
    return data;
}

function showAddServerModal() {
    showModal('新增服务器', getServerFormHtml(null), [
        { text: '取消', class: 'btn-secondary', action: hideModal },
        {
            text: '添加',
            class: 'btn-primary',
            action: async () => {
                const errorDiv = document.getElementById('serverError');
                const serverData = getServerFormData(false);

                if (!serverData.name || !serverData.host || !serverData.username || !serverData.password) {
                    errorDiv.textContent = '请填写必填项（名称、IP、用户名、密码）';
                    errorDiv.style.display = 'block';
                    return;
                }

                const result = await apiRequest('/api/servers', {
                    method: 'POST',
                    body: serverData
                });

                if (result && result.success) {
                    hideModal();
                    await loadServers();
                    // 添加成功后自动连接服务器
                    const newServerId = result.data && result.data.id ? result.data.id : null;
                    if (newServerId) {
                        await connectServer(newServerId);
                    }
                } else {
                    errorDiv.textContent = result ? result.message : '添加失败';
                    errorDiv.style.display = 'block';
                }
            }
        }
    ]);
}

function showEditServerModal(serverId) {
    const server = AppState.servers.find(s => s.id === serverId);
    if (!server) return;

    showModal('编辑服务器', getServerFormHtml(server), [
        { text: '取消', class: 'btn-secondary', action: hideModal },
        {
            text: '保存并重新连接',
            class: 'btn-primary',
            action: async () => {
                const errorDiv = document.getElementById('serverError');
                const serverData = getServerFormData(true);

                if (!serverData.name || !serverData.host || !serverData.username) {
                    errorDiv.textContent = '请填写必填项（名称、IP、用户名）';
                    errorDiv.style.display = 'block';
                    return;
                }

                // 先更新服务器信息
                const updateResult = await apiRequest(`/api/servers/${serverId}`, {
                    method: 'PUT',
                    body: serverData
                });

                if (!updateResult || !updateResult.success) {
                    errorDiv.textContent = updateResult ? updateResult.message : '更新失败';
                    errorDiv.style.display = 'block';
                    return;
                }

                hideModal();
                // 重新加载列表后执行连接
                await loadServers();
                await connectServer(serverId);
            }
        }
    ]);
}

// ==================== 连接服务器（带状态流转提示） ====================
async function connectServer(serverId) {
    const server = AppState.servers.find(s => s.id === serverId);
    const serverName = server ? server.name : `服务器#${serverId}`;

    // 显示状态流转弹窗
    const steps = [
        { key: 'ssh_connect', label: 'SSH 连接中...' },
        { key: 'basic_info', label: '正在获取基本信息...' },
        { key: 'web_root_check', label: '正在检查网站根目录...' },
        { key: 'mysql_check', label: '正在检测 MySQL 连接...' },
        { key: 'finish', label: '保存服务器信息...' }
    ];

    function renderStatusFlow(currentStep, stepStatus, message) {
        const stepsHtml = steps.map(step => {
            let cls = '';
            let icon = '';
            if (step.key === currentStep) {
                cls = stepStatus === 'error' ? 'error' : 'active';
                icon = stepStatus === 'error' ? '✗' : '●';
            } else if (steps.findIndex(s => s.key === step.key) < steps.findIndex(s => s.key === currentStep)) {
                cls = 'done';
                icon = '✓';
            } else {
                icon = '○';
            }
            return `
                <div class="connect-status-step ${cls}">
                    <span class="connect-status-dot"></span>
                    <span>${icon} ${step.label}</span>
                </div>
            `;
        }).join('');

        const msgHtml = message ? `<div style="margin-top:0.5rem;color:var(--text-secondary);font-size:0.8rem;">${escapeHtml(message)}</div>` : '';

        return `
            <div class="connect-status-flow">
                <div style="font-weight:600;margin-bottom:0.5rem;">正在连接: ${escapeHtml(serverName)}</div>
                ${stepsHtml}
                ${msgHtml}
            </div>
        `;
    }

    // 初始显示弹窗
    showModal('连接服务器', renderStatusFlow('ssh_connect', 'active', '正在建立 SSH 连接...'), []);

    let currentData = {};

    // 步骤1: SSH 连接
    let result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'ssh_connect' }
    });

    if (!result || !result.success) {
        document.getElementById('modalBody').innerHTML = renderStatusFlow('ssh_connect', 'error', result ? result.message : 'SSH 连接失败');
        setTimeout(() => {
            hideModal();
            alert(result ? result.message : '连接失败');
        }, 1500);
        return;
    }

    // 步骤2: 基本信息
    document.getElementById('modalBody').innerHTML = renderStatusFlow('basic_info', 'active', '已连接，正在采集系统信息...');
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'basic_info' }
    });
    if (result && result.data) {
        currentData = { ...currentData, ...result.data };
    }

    // 步骤3: Web根目录检查
    document.getElementById('modalBody').innerHTML = renderStatusFlow('web_root_check', 'active', '正在检查网站根目录...');
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'web_root_check' }
    });
    if (result && result.web_root_status) {
        currentData.web_root_status = result.web_root_status;
    }

    // 步骤4: MySQL 检查
    document.getElementById('modalBody').innerHTML = renderStatusFlow('mysql_check', 'active', '正在检测数据库连接...');
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'mysql_check' }
    });
    if (result && result.mysql_conn_status) {
        currentData.mysql_conn_status = result.mysql_conn_status;
    }

    // 步骤5: 保存
    document.getElementById('modalBody').innerHTML = renderStatusFlow('finish', 'active', '正在保存采集结果...');
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: {
            step: 'finish',
            web_root_status: currentData.web_root_status || 'unknown',
            mysql_conn_status: currentData.mysql_conn_status || 'unknown'
        }
    });

    if (result && result.success) {
        document.getElementById('modalBody').innerHTML = renderStatusFlow('finish', 'done', '连接成功，信息已更新！');
        setTimeout(() => {
            hideModal();
            loadServers();
        }, 800);
    } else {
        document.getElementById('modalBody').innerHTML = renderStatusFlow('finish', 'error', result ? result.message : '保存失败');
        setTimeout(() => {
            hideModal();
            alert(result ? result.message : '保存失败');
        }, 1500);
    }
}

async function deleteServer(serverId) {
    if (!confirm('确定要删除这台服务器吗？此操作不可恢复。')) return;

    const result = await apiRequest(`/api/servers/${serverId}`, { method: 'DELETE' });
    if (result && result.success) {
        loadServers();
    } else {
        alert(result ? result.message : '删除失败');
    }
}

// ==================== 服务器详情展示（分板块） ====================
function showServerDetail(serverId) {
    const server = AppState.servers.find(s => s.id === serverId);
    if (!server) return;

    // 解析JSON字段
    let openPorts = [], processes = [], backdoorUsers = [], privEscFiles = [];
    let networkInfo = {}, systemInfo = {}, webServices = {}, dbInfo = {}, cacheInfo = {};
    let userSecurity = {}, cronInfo = {}, writableDirs = {}, flagInfo = {};
    let portProcesses = {}, securityHardening = {}, environmentInfo = {};

    try { openPorts = JSON.parse(server.open_ports || '[]'); } catch (e) {}
    try { processes = JSON.parse(server.processes || '[]'); } catch (e) {}
    try { backdoorUsers = JSON.parse(server.backdoor_users || '[]'); } catch (e) {}
    try { privEscFiles = JSON.parse(server.priv_esc_files || '[]'); } catch (e) {}
    try { networkInfo = JSON.parse(server.network_info || '{}'); } catch (e) {}
    try { systemInfo = JSON.parse(server.system_info || '{}'); } catch (e) {}
    try { webServices = JSON.parse(server.web_services || '{}'); } catch (e) {}
    try { dbInfo = JSON.parse(server.db_info || '{}'); } catch (e) {}
    try { cacheInfo = JSON.parse(server.cache_info || '{}'); } catch (e) {}
    try { userSecurity = JSON.parse(server.user_security || '{}'); } catch (e) {}
    try { cronInfo = JSON.parse(server.cron_info || '{}'); } catch (e) {}
    try { writableDirs = JSON.parse(server.writable_dirs || '{}'); } catch (e) {}
    try { flagInfo = JSON.parse(server.flag_info || '{}'); } catch (e) {}
    try { portProcesses = JSON.parse(server.port_processes || '{}'); } catch (e) {}
    try { securityHardening = JSON.parse(server.security_hardening || '{}'); } catch (e) {}
    try { environmentInfo = JSON.parse(server.environment_info || '{}'); } catch (e) {}

    const webRootBadge = getWebRootBadge(server.web_root_status);
    const mysqlBadge = getMysqlBadge(server.mysql_conn_status);

    // 构建分板块详情内容
    const sections = [];

    // 1. 基本信息
    sections.push({
        title: '基本信息',
        icon: '●',
        content: `
            <div class="detail-grid">
                <div class="detail-item"><span class="detail-label">名称:</span><span class="detail-value">${escapeHtml(server.name)}</span></div>
                <div class="detail-item"><span class="detail-label">类型:</span><span class="detail-value">${server.server_type === 'own' ? '己方' : '夺取'}</span></div>
                <div class="detail-item"><span class="detail-label">IP:</span><span class="detail-value">${escapeHtml(server.host)}:${server.port}</span></div>
                <div class="detail-item"><span class="detail-label">用户:</span><span class="detail-value">${escapeHtml(server.username)}</span></div>
                <div class="detail-item"><span class="detail-label">内核:</span><span class="detail-value">${escapeHtml(server.kernel_version || '未采集')}</span></div>
                <div class="detail-item"><span class="detail-label">PHP:</span><span class="detail-value">${escapeHtml(server.php_version || '未采集')}</span></div>
                <div class="detail-item"><span class="detail-label">MySQL:</span><span class="detail-value">${escapeHtml(server.mysql_version || '未采集')}</span></div>
                <div class="detail-item"><span class="detail-label">Web根目录:</span><span class="detail-value">${escapeHtml(server.web_root)}</span></div>
            </div>
            <div style="margin-top:0.5rem;">${webRootBadge} ${mysqlBadge}</div>
            <div style="margin-top:1rem;display:flex;gap:0.5rem;">
                <button class="btn btn-sm btn-secondary" onclick="showSSHPasswordModal(${server.id}, '${escapeHtml(server.username)}')">修改SSH密码</button>
                <button class="btn btn-sm btn-secondary" onclick="showMySQLPasswordModal(${server.id}, '${escapeHtml(server.db_user || 'root')}')">修改MySQL密码</button>
            </div>
        `
    });

    // 2. 网络信息
    if (networkInfo.ip_addresses || networkInfo.network_segments) {
        sections.push({
            title: '网络信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">IP地址</div>
                    <div class="detail-code">${(networkInfo.ip_addresses || []).map(ip => escapeHtml(ip)).join('<br>') || '未采集'}</div>
                    <div class="detail-subtitle">网段</div>
                    <div class="detail-code">${(networkInfo.network_segments || []).map(s => escapeHtml(s)).join('<br>') || '未采集'}</div>
                    <div class="detail-subtitle">路由</div>
                    <div class="detail-code">${escapeHtml(networkInfo.routes || '未采集')}</div>
                    <div class="detail-subtitle">DNS</div>
                    <div class="detail-code">${escapeHtml(networkInfo.dns || '未采集')}</div>
                    <div class="detail-subtitle">hosts</div>
                    <div class="detail-code">${escapeHtml(networkInfo.hosts || '未采集')}</div>
                    <div class="detail-subtitle">ARP</div>
                    <div class="detail-code">${escapeHtml(networkInfo.arp || '未采集')}</div>
                </div>
            `
        });
    }

    // 3. 系统信息
    if (systemInfo.kernel_name || systemInfo.hostname) {
        sections.push({
            title: '系统信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">内核信息</div>
                    <div class="detail-code">${escapeHtml(systemInfo.kernel_name || '')} ${escapeHtml(systemInfo.kernel_version || '')}</div>
                    <div class="detail-subtitle">主机名</div>
                    <div class="detail-code">${escapeHtml(systemInfo.hostname || '未采集')}</div>
                    <div class="detail-subtitle">架构</div>
                    <div class="detail-code">${escapeHtml(systemInfo.architecture || '未采集')}</div>
                    <div class="detail-subtitle">发行版</div>
                    <div class="detail-code">${escapeHtml(systemInfo.os_release || '未采集')}</div>
                    <div class="detail-subtitle">/proc/version</div>
                    <div class="detail-code">${escapeHtml(systemInfo.proc_version || '未采集')}</div>
                </div>
            `
        });
    }

    // 4. Web服务
    if (webServices.php_version || webServices.apache_version || webServices.nginx_version) {
        sections.push({
            title: 'Web服务',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">PHP版本</div>
                    <div class="detail-code">${escapeHtml(webServices.php_version || '未安装')}</div>
                    <div class="detail-subtitle">PHP安全配置</div>
                    <div class="detail-code">${escapeHtml(webServices.php_security || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">Apache</div>
                    <div class="detail-code">${escapeHtml(webServices.apache_version || '未安装')}</div>
                    <div class="detail-subtitle">Nginx</div>
                    <div class="detail-code">${escapeHtml(webServices.nginx_version || '未安装')}</div>
                </div>
            `
        });
    }

    // 5. 数据库
    if (dbInfo.mysql_version) {
        sections.push({
            title: '数据库信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">MySQL版本</div>
                    <div class="detail-code">${escapeHtml(dbInfo.mysql_version || '未安装')}</div>
                    <div class="detail-subtitle">bind-address</div>
                    <div class="detail-code">${escapeHtml(dbInfo.mysql_bind || '未配置')}</div>
                    <div class="detail-subtitle">弱密码检测</div>
                    <div class="detail-code">${(dbInfo.weak_passwords || []).length > 0 ? '发现弱密码: ' + (dbInfo.weak_passwords || []).join(', ') : '未发现弱密码'}</div>
                </div>
            `
        });
    }

    // 6. 缓存服务
    if (cacheInfo.redis_version) {
        sections.push({
            title: '缓存服务',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">Redis版本</div>
                    <div class="detail-code">${escapeHtml(cacheInfo.redis_version || '未安装')}</div>
                    <div class="detail-subtitle">未授权检测</div>
                    <div class="detail-code">${escapeHtml(cacheInfo.redis_unauth || '未检测')}</div>
                    <div class="detail-subtitle">配置</div>
                    <div class="detail-code">${escapeHtml(cacheInfo.redis_config || '未采集')}</div>
                </div>
            `
        });
    }

    // 7. 用户安全
    if (userSecurity.passwd_content || userSecurity.shadow_readable) {
        sections.push({
            title: '用户安全',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">可登录用户</div>
                    <div class="detail-code">${escapeHtml(userSecurity.login_users || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">UID=0用户</div>
                    <div class="detail-code">${escapeHtml(userSecurity.uid0_users || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">/etc/shadow可读性</div>
                    <div class="detail-code">${escapeHtml(userSecurity.shadow_readable || '未知')}</div>
                    <div class="detail-subtitle">sudo权限</div>
                    <div class="detail-code">${escapeHtml(userSecurity.sudo_privs || '无法获取').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    // 8. 定时任务
    if (cronInfo.system_crontab || cronInfo.cron_d) {
        sections.push({
            title: '定时任务',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">系统crontab</div>
                    <div class="detail-code">${escapeHtml(cronInfo.system_crontab || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">cron.d目录</div>
                    <div class="detail-code">${escapeHtml(cronInfo.cron_d || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">周期任务</div>
                    <div class="detail-code">${escapeHtml(cronInfo.cron_period || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">用户crontab</div>
                    <div class="detail-code">${escapeHtml(cronInfo.user_crontab || '无').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    // 9. 可写入目录
    if (writableDirs.writable_dirs) {
        sections.push({
            title: '文件权限',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">可写入目录</div>
                    <div class="detail-code">${(writableDirs.writable_dirs || []).map(d => escapeHtml(d)).join('<br>') || '无'}</div>
                    <div class="detail-subtitle">Web目录内容</div>
                    <div class="detail-code">${escapeHtml(writableDirs.web_root_content || '未采集').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    // 10. Flag信息
    if (flagInfo.flag_exists !== undefined) {
        sections.push({
            title: 'Flag信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">/flag</div>
                    <div class="detail-code">${flagInfo.flag_exists ? escapeHtml(flagInfo.flag_content || '') : '不存在'}</div>
                    <div class="detail-subtitle">Flag文件搜索</div>
                    <div class="detail-code">${(flagInfo.flag_files || []).map(f => escapeHtml(f)).join('<br>') || '未找到'}</div>
                </div>
            `
        });
    }

    // 11. 端口进程
    if (portProcesses.listening_ports || portProcesses.processes) {
        sections.push({
            title: '端口与进程',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">监听端口</div>
                    <div class="detail-code">${escapeHtml(portProcesses.listening_ports || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">进程列表</div>
                    <div class="detail-code">${escapeHtml(portProcesses.processes || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">进程树</div>
                    <div class="detail-code">${escapeHtml(portProcesses.process_tree || '未采集').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    // 12. 安全加固
    if (securityHardening.suid_files || securityHardening.iptables) {
        sections.push({
            title: '安全加固',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">SUID文件 (${(securityHardening.suid_files || []).length})</div>
                    <div class="detail-code">${(securityHardening.suid_files || []).map(f => escapeHtml(f)).join('<br>') || '无'}</div>
                    <div class="detail-subtitle">SGID文件 (${(securityHardening.sgid_files || []).length})</div>
                    <div class="detail-code">${(securityHardening.sgid_files || []).map(f => escapeHtml(f)).join('<br>') || '无'}</div>
                    <div class="detail-subtitle">iptables</div>
                    <div class="detail-code">${escapeHtml(securityHardening.iptables || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">ASLR</div>
                    <div class="detail-code">${escapeHtml(securityHardening.aslr || '未知')}</div>
                    <div class="detail-subtitle">MAC (SELinux/AppArmor)</div>
                    <div class="detail-code">${escapeHtml(securityHardening.mac || '未安装')}</div>
                </div>
            `
        });
    }

    // 13. 环境信息
    if (environmentInfo.container || environmentInfo.python_version) {
        sections.push({
            title: '环境信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">容器检测</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.container || '未知')}</div>
                    <div class="detail-subtitle">Python</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.python_version || '未安装')}</div>
                    <div class="detail-subtitle">GCC</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.gcc_version || '未安装')}</div>
                    <div class="detail-subtitle">磁盘</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.disk || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">内存</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.memory || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">CPU</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.cpu || '未采集').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }



    // 构建标签页HTML
    const tabsHtml = sections.map((sec, idx) => `
        <button class="detail-tab ${idx === 0 ? 'active' : ''}" data-idx="${idx}" onclick="switchDetailTab(${idx})">
            ${sec.icon} ${sec.title}
        </button>
    `).join('');

    const panelsHtml = sections.map((sec, idx) => `
        <div class="detail-panel ${idx === 0 ? 'active' : ''}" data-idx="${idx}">
            ${sec.content}
        </div>
    `).join('');

    showModal('服务器详情', `
        <div class="server-detail-container">
            <div class="detail-tabs">${tabsHtml}</div>
            <div class="detail-panels">${panelsHtml}</div>
        </div>
    `, [
        { text: '关闭', class: 'btn-secondary', action: hideModal },
        {
            text: '刷新信息',
            class: 'btn-primary',
            action: async () => {
                // 在弹窗内显示刷新状态
                const modalBody = document.getElementById('modalBody');
                const originalContent = modalBody.innerHTML;
                modalBody.innerHTML = `
                    <div style="text-align:center;padding:2rem;">
                        <div style="font-size:1.2rem;color:var(--accent-blue);margin-bottom:1rem;">正在刷新服务器信息...</div>
                        <div style="color:var(--text-secondary);font-size:0.85rem;">请稍候，正在重新连接并采集数据</div>
                    </div>
                `;
                // 执行连接流程
                const refreshResult = await refreshServerInModal(serverId);
                if (refreshResult) {
                    // 重新渲染详情内容
                    await renderServerDetailContent(serverId);
                } else {
                    modalBody.innerHTML = originalContent;
                    alert('刷新失败，请重试');
                }
            }
        }
    ]);
}

async function refreshServerInModal(serverId) {
    // 执行完整的连接流程但不显示连接弹窗
    let currentData = {};

    // 步骤1: SSH 连接
    let result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'ssh_connect' }
    });
    if (!result || !result.success) return false;

    // 步骤2: 基本信息
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'basic_info' }
    });
    if (result && result.data) {
        currentData = { ...currentData, ...result.data };
    }

    // 步骤3: Web根目录检查
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'web_root_check' }
    });
    if (result && result.web_root_status) {
        currentData.web_root_status = result.web_root_status;
    }

    // 步骤4: MySQL 检查
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: { step: 'mysql_check' }
    });
    if (result && result.mysql_conn_status) {
        currentData.mysql_conn_status = result.mysql_conn_status;
    }

    // 步骤5: 保存
    result = await apiRequest(`/api/servers/${serverId}/connect-step`, {
        method: 'POST',
        body: {
            step: 'finish',
            web_root_status: currentData.web_root_status || 'unknown',
            mysql_conn_status: currentData.mysql_conn_status || 'unknown'
        }
    });

    if (result && result.success) {
        // 更新本地服务器列表
        await loadServers();
        return true;
    }
    return false;
}

async function renderServerDetailContent(serverId) {
    const server = AppState.servers.find(s => s.id === serverId);
    if (!server) return;

    // 解析JSON字段
    let openPorts = [], processes = [], backdoorUsers = [], privEscFiles = [];
    let networkInfo = {}, systemInfo = {}, webServices = {}, dbInfo = {}, cacheInfo = {};
    let userSecurity = {}, cronInfo = {}, writableDirs = {}, flagInfo = {};
    let portProcesses = {}, securityHardening = {}, environmentInfo = {};

    try { openPorts = JSON.parse(server.open_ports || '[]'); } catch (e) {}
    try { processes = JSON.parse(server.processes || '[]'); } catch (e) {}
    try { backdoorUsers = JSON.parse(server.backdoor_users || '[]'); } catch (e) {}
    try { privEscFiles = JSON.parse(server.priv_esc_files || '[]'); } catch (e) {}
    try { networkInfo = JSON.parse(server.network_info || '{}'); } catch (e) {}
    try { systemInfo = JSON.parse(server.system_info || '{}'); } catch (e) {}
    try { webServices = JSON.parse(server.web_services || '{}'); } catch (e) {}
    try { dbInfo = JSON.parse(server.db_info || '{}'); } catch (e) {}
    try { cacheInfo = JSON.parse(server.cache_info || '{}'); } catch (e) {}
    try { userSecurity = JSON.parse(server.user_security || '{}'); } catch (e) {}
    try { cronInfo = JSON.parse(server.cron_info || '{}'); } catch (e) {}
    try { writableDirs = JSON.parse(server.writable_dirs || '{}'); } catch (e) {}
    try { flagInfo = JSON.parse(server.flag_info || '{}'); } catch (e) {}
    try { portProcesses = JSON.parse(server.port_processes || '{}'); } catch (e) {}
    try { securityHardening = JSON.parse(server.security_hardening || '{}'); } catch (e) {}
    try { environmentInfo = JSON.parse(server.environment_info || '{}'); } catch (e) {}

    const webRootBadge = getWebRootBadge(server.web_root_status);
    const mysqlBadge = getMysqlBadge(server.mysql_conn_status);

    const sections = [];

    sections.push({
        title: '基本信息',
        icon: '●',
        content: `
            <div class="detail-grid">
                <div class="detail-item"><span class="detail-label">名称:</span><span class="detail-value">${escapeHtml(server.name)}</span></div>
                <div class="detail-item"><span class="detail-label">类型:</span><span class="detail-value">${server.server_type === 'own' ? '己方' : '夺取'}</span></div>
                <div class="detail-item"><span class="detail-label">IP:</span><span class="detail-value">${escapeHtml(server.host)}:${server.port}</span></div>
                <div class="detail-item"><span class="detail-label">用户:</span><span class="detail-value">${escapeHtml(server.username)}</span></div>
                <div class="detail-item"><span class="detail-label">内核:</span><span class="detail-value">${escapeHtml(server.kernel_version || '未采集')}</span></div>
                <div class="detail-item"><span class="detail-label">PHP:</span><span class="detail-value">${escapeHtml(server.php_version || '未采集')}</span></div>
                <div class="detail-item"><span class="detail-label">MySQL:</span><span class="detail-value">${escapeHtml(server.mysql_version || '未采集')}</span></div>
                <div class="detail-item"><span class="detail-label">Web根目录:</span><span class="detail-value">${escapeHtml(server.web_root)}</span></div>
            </div>
            <div style="margin-top:0.5rem;">${webRootBadge} ${mysqlBadge}</div>
        `
    });

    if (networkInfo.ip_addresses || networkInfo.network_segments) {
        sections.push({
            title: '网络信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">IP地址</div>
                    <div class="detail-code">${(networkInfo.ip_addresses || []).map(ip => escapeHtml(ip)).join('<br>') || '未采集'}</div>
                    <div class="detail-subtitle">网段</div>
                    <div class="detail-code">${(networkInfo.network_segments || []).map(s => escapeHtml(s)).join('<br>') || '未采集'}</div>
                    <div class="detail-subtitle">路由</div>
                    <div class="detail-code">${escapeHtml(networkInfo.routes || '未采集')}</div>
                    <div class="detail-subtitle">DNS</div>
                    <div class="detail-code">${escapeHtml(networkInfo.dns || '未采集')}</div>
                    <div class="detail-subtitle">hosts</div>
                    <div class="detail-code">${escapeHtml(networkInfo.hosts || '未采集')}</div>
                    <div class="detail-subtitle">ARP</div>
                    <div class="detail-code">${escapeHtml(networkInfo.arp || '未采集')}</div>
                </div>
            `
        });
    }

    if (systemInfo.kernel_name || systemInfo.hostname) {
        sections.push({
            title: '系统信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">内核信息</div>
                    <div class="detail-code">${escapeHtml(systemInfo.kernel_name || '')} ${escapeHtml(systemInfo.kernel_version || '')}</div>
                    <div class="detail-subtitle">主机名</div>
                    <div class="detail-code">${escapeHtml(systemInfo.hostname || '未采集')}</div>
                    <div class="detail-subtitle">架构</div>
                    <div class="detail-code">${escapeHtml(systemInfo.architecture || '未采集')}</div>
                    <div class="detail-subtitle">发行版</div>
                    <div class="detail-code">${escapeHtml(systemInfo.os_release || '未采集')}</div>
                    <div class="detail-subtitle">/proc/version</div>
                    <div class="detail-code">${escapeHtml(systemInfo.proc_version || '未采集')}</div>
                </div>
            `
        });
    }

    if (webServices.php_version || webServices.apache_version || webServices.nginx_version) {
        sections.push({
            title: 'Web服务',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">PHP版本</div>
                    <div class="detail-code">${escapeHtml(webServices.php_version || '未安装')}</div>
                    <div class="detail-subtitle">PHP安全配置</div>
                    <div class="detail-code">${escapeHtml(webServices.php_security || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">Apache</div>
                    <div class="detail-code">${escapeHtml(webServices.apache_version || '未安装')}</div>
                    <div class="detail-subtitle">Nginx</div>
                    <div class="detail-code">${escapeHtml(webServices.nginx_version || '未安装')}</div>
                </div>
            `
        });
    }

    if (dbInfo.mysql_version) {
        sections.push({
            title: '数据库信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">MySQL版本</div>
                    <div class="detail-code">${escapeHtml(dbInfo.mysql_version || '未安装')}</div>
                    <div class="detail-subtitle">bind-address</div>
                    <div class="detail-code">${escapeHtml(dbInfo.mysql_bind || '未配置')}</div>
                    <div class="detail-subtitle">弱密码检测</div>
                    <div class="detail-code">${(dbInfo.weak_passwords || []).length > 0 ? '发现弱密码: ' + (dbInfo.weak_passwords || []).join(', ') : '未发现弱密码'}</div>
                </div>
            `
        });
    }

    if (cacheInfo.redis_version) {
        sections.push({
            title: '缓存服务',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">Redis版本</div>
                    <div class="detail-code">${escapeHtml(cacheInfo.redis_version || '未安装')}</div>
                    <div class="detail-subtitle">未授权检测</div>
                    <div class="detail-code">${escapeHtml(cacheInfo.redis_unauth || '未检测')}</div>
                    <div class="detail-subtitle">配置</div>
                    <div class="detail-code">${escapeHtml(cacheInfo.redis_config || '未采集')}</div>
                </div>
            `
        });
    }

    if (userSecurity.passwd_content || userSecurity.shadow_readable) {
        sections.push({
            title: '用户安全',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">可登录用户</div>
                    <div class="detail-code">${escapeHtml(userSecurity.login_users || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">UID=0用户</div>
                    <div class="detail-code">${escapeHtml(userSecurity.uid0_users || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">/etc/shadow可读性</div>
                    <div class="detail-code">${escapeHtml(userSecurity.shadow_readable || '未知')}</div>
                    <div class="detail-subtitle">sudo权限</div>
                    <div class="detail-code">${escapeHtml(userSecurity.sudo_privs || '无法获取').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    if (cronInfo.system_crontab || cronInfo.cron_d) {
        sections.push({
            title: '定时任务',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">系统crontab</div>
                    <div class="detail-code">${escapeHtml(cronInfo.system_crontab || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">cron.d目录</div>
                    <div class="detail-code">${escapeHtml(cronInfo.cron_d || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">周期任务</div>
                    <div class="detail-code">${escapeHtml(cronInfo.cron_period || '无').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">用户crontab</div>
                    <div class="detail-code">${escapeHtml(cronInfo.user_crontab || '无').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    if (writableDirs.writable_dirs) {
        sections.push({
            title: '文件权限',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">可写入目录</div>
                    <div class="detail-code">${(writableDirs.writable_dirs || []).map(d => escapeHtml(d)).join('<br>') || '无'}</div>
                    <div class="detail-subtitle">Web目录内容</div>
                    <div class="detail-code">${escapeHtml(writableDirs.web_root_content || '未采集').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    if (flagInfo.flag_exists !== undefined) {
        sections.push({
            title: 'Flag信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">/flag</div>
                    <div class="detail-code">${flagInfo.flag_exists ? escapeHtml(flagInfo.flag_content || '') : '不存在'}</div>
                    <div class="detail-subtitle">Flag文件搜索</div>
                    <div class="detail-code">${(flagInfo.flag_files || []).map(f => escapeHtml(f)).join('<br>') || '未找到'}</div>
                </div>
            `
        });
    }

    if (portProcesses.listening_ports || portProcesses.processes) {
        sections.push({
            title: '端口与进程',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">监听端口</div>
                    <div class="detail-code">${escapeHtml(portProcesses.listening_ports || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">进程列表</div>
                    <div class="detail-code">${escapeHtml(portProcesses.processes || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">进程树</div>
                    <div class="detail-code">${escapeHtml(portProcesses.process_tree || '未采集').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }

    if (securityHardening.suid_files || securityHardening.iptables) {
        sections.push({
            title: '安全加固',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">SUID文件 (${(securityHardening.suid_files || []).length})</div>
                    <div class="detail-code">${(securityHardening.suid_files || []).map(f => escapeHtml(f)).join('<br>') || '无'}</div>
                    <div class="detail-subtitle">SGID文件 (${(securityHardening.sgid_files || []).length})</div>
                    <div class="detail-code">${(securityHardening.sgid_files || []).map(f => escapeHtml(f)).join('<br>') || '无'}</div>
                    <div class="detail-subtitle">iptables</div>
                    <div class="detail-code">${escapeHtml(securityHardening.iptables || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">ASLR</div>
                    <div class="detail-code">${escapeHtml(securityHardening.aslr || '未知')}</div>
                    <div class="detail-subtitle">MAC (SELinux/AppArmor)</div>
                    <div class="detail-code">${escapeHtml(securityHardening.mac || '未安装')}</div>
                </div>
            `
        });
    }

    if (environmentInfo.container || environmentInfo.python_version) {
        sections.push({
            title: '环境信息',
            icon: '◆',
            content: `
                <div class="detail-section">
                    <div class="detail-subtitle">容器检测</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.container || '未知')}</div>
                    <div class="detail-subtitle">Python</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.python_version || '未安装')}</div>
                    <div class="detail-subtitle">GCC</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.gcc_version || '未安装')}</div>
                    <div class="detail-subtitle">磁盘</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.disk || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">内存</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.memory || '未采集').replace(/\n/g, '<br>')}</div>
                    <div class="detail-subtitle">CPU</div>
                    <div class="detail-code">${escapeHtml(environmentInfo.cpu || '未采集').replace(/\n/g, '<br>')}</div>
                </div>
            `
        });
    }



    const tabsHtml = sections.map((sec, idx) => `
        <button class="detail-tab ${idx === 0 ? 'active' : ''}" data-idx="${idx}" onclick="switchDetailTab(${idx})">
            ${sec.icon} ${sec.title}
        </button>
    `).join('');

    const panelsHtml = sections.map((sec, idx) => `
        <div class="detail-panel ${idx === 0 ? 'active' : ''}" data-idx="${idx}">
            ${sec.content}
        </div>
    `).join('');

    const modalBody = document.getElementById('modalBody');
    modalBody.innerHTML = `
        <div class="server-detail-container">
            <div class="detail-tabs">${tabsHtml}</div>
            <div class="detail-panels">${panelsHtml}</div>
        </div>
    `;
}

function switchDetailTab(idx) {
    document.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.detail-panel').forEach(p => p.classList.remove('active'));
    const tab = document.querySelector(`.detail-tab[data-idx="${idx}"]`);
    const panel = document.querySelector(`.detail-panel[data-idx="${idx}"]`);
    if (tab) tab.classList.add('active');
    if (panel) panel.classList.add('active');
}

// ==================== 监控数据加载 ====================
function loadMonitorData() {
    // 文件监控和进程监控数据在各自的模块中加载
}

// ==================== 全局控制服务器 ====================
function getOnlineServers() {
    return AppState.servers.filter(s => s.status === 'online');
}

function getControlServer() {
    return AppState.servers.find(s => s.id === AppState.controlServerId) || null;
}

function ensureControlServer() {
    const onlineServers = getOnlineServers();
    const currentStillOnline = onlineServers.some(s => s.id === AppState.controlServerId);
    if (!currentStillOnline) {
        AppState.controlServerId = onlineServers.length > 0 ? onlineServers[0].id : null;
    }
    AppState.selectedServer = AppState.controlServerId;
}

function renderControlServerText() {
    const server = getControlServer();
    if (!server) {
        return '<span class="control-server-empty">当前控制服务器: 无在线服务器</span>';
    }
    return `
        <button class="control-server-btn" onclick="showControlServerSwitcher()" title="点击切换当前控制服务器">
            <span class="control-server-dot"></span>
            <span class="control-server-label">当前控制服务器:</span>
            <strong>${escapeHtml(server.name)}</strong>
            <span class="control-server-host">${escapeHtml(server.host)}</span>
            <span class="control-server-caret">▾</span>
        </button>
    `;
}

function showControlServerSwitcher() {
    const onlineServers = getOnlineServers();
    if (onlineServers.length === 0) {
        alert('暂无在线服务器，请先连接服务器');
        return;
    }

    const bodyHtml = `
        <div class="control-switcher-list">
            ${onlineServers.map(server => `
                <button class="control-switcher-item ${server.id === AppState.controlServerId ? 'active' : ''}" onclick="setControlServer(${server.id}); hideModal();">
                    <span class="control-server-dot"></span>
                    <span class="control-switcher-main">
                        <strong>${escapeHtml(server.name)}</strong>
                        <small>${escapeHtml(server.host)}:${server.port}</small>
                    </span>
                    <span class="control-switcher-type">${server.server_type === 'own' ? '己方' : '夺取'}</span>
                </button>
            `).join('')}
        </div>
    `;
    showModal('切换当前控制服务器', bodyHtml, [
        { text: '关闭', class: 'btn-secondary', action: hideModal }
    ]);
}

function setControlServer(serverId) {
    const server = AppState.servers.find(s => s.id === serverId && s.status === 'online');
    if (!server) {
        alert('只能切换到在线服务器');
        return;
    }
    AppState.controlServerId = serverId;
    AppState.selectedServer = serverId;
    updateStatusBar();
    refreshCurrentControlPanel();
}

function refreshCurrentControlPanel() {
    if (AppState.currentTab === 'backup') {
        initBackupPage();
    } else if (AppState.currentTab === 'waf') {
        initWAFPage();
    } else if (AppState.currentTab === 'scripts') {
        initScriptsPage();
    } else if (AppState.currentTab === 'monitor') {
        initMonitorPage();
        loadMonitorData();
    }
}

// ==================== 状态栏更新 ====================
function updateStatusBar() {
    const onlineCount = getOnlineServers().length;
    const controlEl = document.getElementById('statusControlServer');
    if (controlEl) controlEl.innerHTML = renderControlServerText();
    document.getElementById('statusOnline').textContent = `在线服务器: ${onlineCount}`;
}

// ==================== 告警 ====================
function playAlarmSound() {
    const audio = document.getElementById('alarmSound');
    if (audio) {
        console.log('[告警] 播放音效, audio元素:', audio);
        // 重置播放位置并播放
        audio.currentTime = 0;
        audio.play().then(() => {
            console.log('[告警] 音效播放成功');
        }).catch((e) => {
            console.error('[告警] 音效播放失败:', e);
        });
    } else {
        console.error('[告警] 未找到audio元素');
    }
}

// ==================== 工具函数 ====================
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getSeverityText(severity) {
    const map = { 'critical': '严重', 'warning': '警告', 'info': '信息' };
    return map[severity] || severity;
}

// ==================== 密码修改 ====================
function validatePasswordStrength(password) {
    if (password.length < 12) {
        return { valid: false, message: '密码长度至少12位' };
    }
    if (!/[a-z]/.test(password)) {
        return { valid: false, message: '密码需包含小写字母' };
    }
    if (!/[A-Z]/.test(password)) {
        return { valid: false, message: '密码需包含大写字母' };
    }
    if (!/\d/.test(password)) {
        return { valid: false, message: '密码需包含数字' };
    }
    if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)) {
        return { valid: false, message: '密码需包含特殊字符' };
    }
    return { valid: true, message: '' };
}

function showSSHPasswordModal(serverId, username) {
    const formHtml = `
        <div class="form-group">
            <label>当前用户</label>
            <input type="text" value="${escapeHtml(username)}" readonly style="background:var(--bg-secondary);">
        </div>
        <div class="form-group">
            <label>新密码 *</label>
            <input type="password" id="newSSHPassword" placeholder="至少12位，含大小写字母、数字、特殊字符">
        </div>
        <div class="form-group">
            <label>确认密码 *</label>
            <input type="password" id="confirmSSHPassword" placeholder="再次输入新密码">
        </div>
        <div id="sshPasswordProgress" style="display:none;margin-top:1rem;">
            <div style="font-size:0.85rem;color:var(--text-secondary);">
                <div id="sshProgressStep1">⏳ 正在连接服务器...</div>
                <div id="sshProgressStep2" style="display:none;">⏳ 正在验证旧密码...</div>
                <div id="sshProgressStep3" style="display:none;">⏳ 正在修改密码...</div>
                <div id="sshProgressStep4" style="display:none;">⏳ 正在验证新密码...</div>
            </div>
        </div>
        <div id="sshPasswordError" style="color:var(--accent-red);font-size:0.85rem;display:none;"></div>
        <div id="sshPasswordSuccess" style="color:var(--accent-green);font-size:0.85rem;display:none;"></div>
    `;
    
    showModal('修改SSH密码', formHtml, [
        { text: '取消', class: 'btn-secondary', action: hideModal },
        { text: '确认修改', class: 'btn-primary', action: () => doChangeSSHPassword(serverId) }
    ]);
}

async function doChangeSSHPassword(serverId) {
    const newPassword = document.getElementById('newSSHPassword').value;
    const confirmPassword = document.getElementById('confirmSSHPassword').value;
    const errorDiv = document.getElementById('sshPasswordError');
    const successDiv = document.getElementById('sshPasswordSuccess');
    const progressDiv = document.getElementById('sshPasswordProgress');
    
    // 校验
    const validation = validatePasswordStrength(newPassword);
    if (!validation.valid) {
        errorDiv.textContent = validation.message;
        errorDiv.style.display = 'block';
        return;
    }
    
    if (newPassword !== confirmPassword) {
        errorDiv.textContent = '两次输入的密码不一致';
        errorDiv.style.display = 'block';
        return;
    }
    
    // 显示进度
    errorDiv.style.display = 'none';
    successDiv.style.display = 'none';
    progressDiv.style.display = 'block';
    
    // 禁用按钮
    const modalButtons = document.querySelectorAll('.modal-footer .btn');
    modalButtons.forEach(btn => btn.disabled = true);
    
    try {
        // 步骤1: 连接服务器
        document.getElementById('sshProgressStep1').style.display = 'block';
        
        // 调用API
        const result = await apiRequest(`/api/servers/${serverId}/password/ssh`, {
            method: 'POST',
            body: { new_password: newPassword }
        });
        
        // 更新进度显示
        if (result && result.progress) {
            result.progress.forEach(step => {
                const stepDiv = document.getElementById(`sshProgressStep${step.num}`);
                if (stepDiv) {
                    stepDiv.style.display = 'block';
                    stepDiv.textContent = step.success ? `✅ ${step.text}` : `❌ ${step.text}`;
                }
            });
        }
        
        if (result && result.success) {
            successDiv.textContent = '✅ SSH密码修改成功！';
            successDiv.style.display = 'block';
            progressDiv.style.display = 'none';
            
            // 2秒后关闭模态框
            setTimeout(() => {
                hideModal();
                loadServers();
            }, 1500);
        } else {
            errorDiv.textContent = result ? result.message : '修改失败';
            errorDiv.style.display = 'block';
            progressDiv.style.display = 'none';
            modalButtons.forEach(btn => btn.disabled = false);
        }
    } catch (e) {
        errorDiv.textContent = '请求失败: ' + e.message;
        errorDiv.style.display = 'block';
        progressDiv.style.display = 'none';
        modalButtons.forEach(btn => btn.disabled = false);
    }
}

function showMySQLPasswordModal(serverId, dbUser) {
    const formHtml = `
        <div class="form-group">
            <label>数据库用户</label>
            <input type="text" value="${escapeHtml(dbUser)}" readonly style="background:var(--bg-secondary);">
        </div>
        <div class="form-group">
            <label>新密码 *</label>
            <input type="password" id="newMySQLPassword" placeholder="至少12位，含大小写字母、数字、特殊字符">
        </div>
        <div class="form-group">
            <label>确认密码 *</label>
            <input type="password" id="confirmMySQLPassword" placeholder="再次输入新密码">
        </div>
        <div id="mysqlPasswordProgress" style="display:none;margin-top:1rem;">
            <div style="font-size:0.85rem;color:var(--text-secondary);">
                <div id="mysqlProgressStep1">⏳ 正在连接服务器...</div>
                <div id="mysqlProgressStep2" style="display:none;">⏳ 正在连接MySQL...</div>
                <div id="mysqlProgressStep3" style="display:none;">⏳ 正在修改密码...</div>
                <div id="mysqlProgressStep4" style="display:none;">⏳ 正在验证新密码...</div>
            </div>
        </div>
        <div id="mysqlPasswordError" style="color:var(--accent-red);font-size:0.85rem;display:none;"></div>
        <div id="mysqlPasswordSuccess" style="color:var(--accent-green);font-size:0.85rem;display:none;"></div>
    `;
    
    showModal('修改MySQL密码', formHtml, [
        { text: '取消', class: 'btn-secondary', action: hideModal },
        { text: '确认修改', class: 'btn-primary', action: () => doChangeMySQLPassword(serverId) }
    ]);
}

async function doChangeMySQLPassword(serverId) {
    const newPassword = document.getElementById('newMySQLPassword').value;
    const confirmPassword = document.getElementById('confirmMySQLPassword').value;
    const errorDiv = document.getElementById('mysqlPasswordError');
    const successDiv = document.getElementById('mysqlPasswordSuccess');
    const progressDiv = document.getElementById('mysqlPasswordProgress');
    
    // 校验
    const validation = validatePasswordStrength(newPassword);
    if (!validation.valid) {
        errorDiv.textContent = validation.message;
        errorDiv.style.display = 'block';
        return;
    }
    
    if (newPassword !== confirmPassword) {
        errorDiv.textContent = '两次输入的密码不一致';
        errorDiv.style.display = 'block';
        return;
    }
    
    // 显示进度
    errorDiv.style.display = 'none';
    successDiv.style.display = 'none';
    progressDiv.style.display = 'block';
    
    // 禁用按钮
    const modalButtons = document.querySelectorAll('.modal-footer .btn');
    modalButtons.forEach(btn => btn.disabled = true);
    
    try {
        // 步骤1: 连接服务器
        document.getElementById('mysqlProgressStep1').style.display = 'block';
        
        // 调用API
        const result = await apiRequest(`/api/servers/${serverId}/password/mysql`, {
            method: 'POST',
            body: { new_password: newPassword }
        });
        
        // 更新进度显示
        if (result && result.progress) {
            result.progress.forEach(step => {
                const stepDiv = document.getElementById(`mysqlProgressStep${step.num}`);
                if (stepDiv) {
                    stepDiv.style.display = 'block';
                    stepDiv.textContent = step.success ? `✅ ${step.text}` : `❌ ${step.text}`;
                }
            });
        }
        
        if (result && result.success) {
            successDiv.textContent = '✅ MySQL密码修改成功！';
            successDiv.style.display = 'block';
            progressDiv.style.display = 'none';
            
            // 1.5秒后关闭模态框
            setTimeout(() => {
                hideModal();
                loadServers();
            }, 1500);
        } else {
            errorDiv.textContent = result ? result.message : '修改失败';
            errorDiv.style.display = 'block';
            progressDiv.style.display = 'none';
            modalButtons.forEach(btn => btn.disabled = false);
        }
    } catch (e) {
        errorDiv.textContent = '请求失败: ' + e.message;
        errorDiv.style.display = 'block';
        progressDiv.style.display = 'none';
        modalButtons.forEach(btn => btn.disabled = false);
    }
}

// ==================== 初始化 ====================
async function init() {
    // 检查登录状态
    const isAuth = await checkAuth();
    if (!isAuth) return;

    // 初始化标签页
    initTabs();

    // 绑定事件
    document.getElementById('logoutBtn').addEventListener('click', logout);
    document.getElementById('changePasswordBtn').addEventListener('click', showChangePasswordModal);
    document.getElementById('addServerBtn').addEventListener('click', showAddServerModal);
    document.getElementById('modalClose').addEventListener('click', hideModal);

    // 加载初始数据
    loadServers();
}

// 启动应用
document.addEventListener('DOMContentLoaded', init);
