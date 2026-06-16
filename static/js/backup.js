/**
 * 备份恢复前端逻辑
 */

// ==================== 备份恢复页面 ====================
function initBackupPage() {
    const content = document.getElementById('backupContent');
    content.innerHTML = `
        <div class="backup-selector">
            <div class="form-group">
                <label>选择服务器</label>
                <select id="backupServerSelect" onchange="loadBackupServer()">
                    <option value="">-- 请选择服务器 --</option>
                    ${AppState.servers.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.host)})</option>`).join('')}
                </select>
            </div>
        </div>
        <div id="backupServerContent" style="display:none;">
            <div class="backup-tabs">
                <button class="monitor-tab-btn active" data-btype="web" onclick="switchBackupType('web')">网站备份</button>
                <button class="monitor-tab-btn" data-btype="database" onclick="switchBackupType('database')">数据库备份</button>
            </div>
            <div class="backup-action-panel">
                <div class="card">
                    <div class="card-header">
                        <span class="card-title">一键备份</span>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>版本标签</label>
                            <input type="text" id="backupVersionTag" placeholder="如: 初始备份、修复后备份">
                        </div>
                        <div class="form-group" id="storageDirGroup" style="display:none;">
                            <label>存储目录</label>
                            <select id="backupStorageDir" style="width:100%;">
                                <option value="/tmp">/tmp</option>
                            </select>
                        </div>
                        <div class="form-group" style="display:flex;align-items:flex-end;">
                            <button class="btn btn-primary" id="backupBtn" onclick="doBackup()">一键备份</button>
                        </div>
                    </div>
                </div>
            </div>
            <div class="backup-history">
                <h3 style="margin-bottom:0.75rem;">备份历史</h3>
                <div id="backupHistoryList"></div>
            </div>
        </div>
    `;
}

function switchBackupType(type) {
    AppState.backupType = type;
    document.querySelectorAll('.backup-tabs .monitor-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.btype === type);
    });
    const storageDirGroup = document.getElementById('storageDirGroup');
    if (storageDirGroup) storageDirGroup.style.display = type === 'web' ? 'block' : 'none';
    loadBackupHistory();
}

async function loadBackupServer() {
    const serverId = document.getElementById('backupServerSelect').value;
    const content = document.getElementById('backupServerContent');
    if (!serverId) {
        content.style.display = 'none';
        return;
    }
    content.style.display = 'block';
    AppState.selectedServer = parseInt(serverId);
    AppState.backupType = 'web';

    const storageDirGroup = document.getElementById('storageDirGroup');
    if (storageDirGroup) storageDirGroup.style.display = 'block';

    await loadWritableDirs(parseInt(serverId));
    loadBackupHistory();
}

async function loadWritableDirs(serverId) {
    const select = document.getElementById('backupStorageDir');
    if (!select) return;

    // 从API实时探测服务器上的可写入目录
    let writableDirs = [];
    try {
        const result = await apiRequest(`/api/servers/${serverId}/writable-dirs`);
        if (result && result.success && Array.isArray(result.data)) {
            writableDirs = result.data;
        }
    } catch (e) {
        console.log('获取可写入目录失败:', e);
    }

    // 构建选项，默认/tmp选中
    let options = '';
    const seen = new Set();

    // 确保/tmp在最前面且默认选中
    options += '<option value="/tmp" selected>/tmp</option>';
    seen.add('/tmp');

    // 添加其他可写入目录
    if (writableDirs.length > 0) {
        writableDirs.forEach(d => {
            if (!seen.has(d)) {
                options += `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`;
                seen.add(d);
            }
        });
    }

    // 添加固定候选目录（如果不在列表中）
    const candidates = ['/var/tmp', '/dev/shm', '/var/www/html', '/var/www', '/home'];
    candidates.forEach(d => {
        if (!seen.has(d)) {
            options += `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`;
            seen.add(d);
        }
    });

    // 手动输入选项
    options += '<option value="__custom__">手动输入...</option>';
    select.innerHTML = options;

    // 手动输入处理
    select.onchange = function() {
        let customInput = document.getElementById('backupStorageDirCustom');
        if (this.value === '__custom__') {
            if (!customInput) {
                customInput = document.createElement('input');
                customInput.id = 'backupStorageDirCustom';
                customInput.type = 'text';
                customInput.placeholder = '输入存储目录路径';
                customInput.style.cssText = 'width:100%;margin-top:0.4rem;';
                select.parentNode.appendChild(customInput);
            }
            customInput.style.display = 'block';
            customInput.focus();
        } else {
            if (customInput) customInput.style.display = 'none';
        }
    };
}

function getStorageDir() {
    const select = document.getElementById('backupStorageDir');
    if (!select) return '/tmp';
    if (select.value === '__custom__') {
        const customInput = document.getElementById('backupStorageDirCustom');
        return customInput && customInput.value.trim() ? customInput.value.trim() : '/tmp';
    }
    return select.value;
}

async function doBackup() {
    const serverId = AppState.selectedServer;
    const versionTag = document.getElementById('backupVersionTag').value.trim();
    const type = AppState.backupType || 'web';

    if (!versionTag) {
        alert('请输入版本标签');
        return;
    }

    const btn = document.getElementById('backupBtn');
    btn.disabled = true;
    btn.textContent = '备份中...';

    let body = { version_tag: versionTag };
    if (type === 'web') {
        body.storage_dir = getStorageDir();
    }

    const result = await apiRequest(`/api/servers/${serverId}/backup/${type}`, {
        method: 'POST',
        body: body
    });

    btn.disabled = false;
    btn.textContent = '一键备份';

    if (result && result.success) {
        alert(`${type === 'web' ? '网站' : '数据库'}备份成功！文件已同步到本地。`);
        document.getElementById('backupVersionTag').value = '';
        loadBackupHistory();
    } else {
        alert(result ? result.message : '备份失败');
    }
}

async function loadBackupHistory() {
    const serverId = AppState.selectedServer;
    if (!serverId) return;

    const type = AppState.backupType || 'web';
    const result = await apiRequest(`/api/servers/${serverId}/backups?type=${type}`);
    if (!result || !result.success) return;

    const container = document.getElementById('backupHistoryList');
    const backups = result.data || [];

    if (backups.length === 0) {
        container.innerHTML = '<p class="placeholder-text">暂无备份记录</p>';
        return;
    }

    container.innerHTML = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>版本标签</th>
                        <th>类型</th>
                        <th>文件大小</th>
                        <th>备份时间</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${backups.map(b => `
                        <tr>
                            <td><strong>${escapeHtml(b.version_tag)}</strong></td>
                            <td><span class="badge badge-${b.backup_type === 'web' ? 'info' : 'warning'}">${b.backup_type === 'web' ? '网站' : '数据库'}</span></td>
                            <td>${formatFileSize(b.file_size)}</td>
                            <td>${b.created_at}</td>
                            <td>
                                <button class="btn btn-sm btn-success" onclick="doRestore(${b.id}, '${b.backup_type}')">恢复</button>
                                <button class="btn btn-sm btn-danger" onclick="doDeleteLocal(${b.id}, '${escapeHtml(b.version_tag)}')">删除本地</button>
                                <button class="btn btn-sm btn-warning" onclick="doDeleteOnline(${b.id}, '${escapeHtml(b.version_tag)}')">删除线上</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function doRestore(backupId, type) {
    if (!confirm(`确定要恢复到这个版本吗？当前数据将被覆盖！`)) return;

    const serverId = AppState.selectedServer;
    const result = await apiRequest(`/api/servers/${serverId}/restore/${type}/${backupId}`, {
        method: 'POST'
    });

    if (result && result.success) {
        alert(result.message);
    } else {
        alert(result ? result.message : '恢复失败');
    }
}

async function doDeleteLocal(backupId, versionTag) {
    if (!confirm(`确定要删除本地备份 "${versionTag}" 吗？\n本地备份文件将被删除，线上临时文件保留。`)) return;

    const result = await apiRequest(`/api/backups/${backupId}`, {
        method: 'DELETE',
        body: { delete_local: true, delete_online: false }
    });
    if (result && result.success) {
        loadBackupHistory();
    } else {
        alert(result ? result.message : '删除失败');
    }
}

async function doDeleteOnline(backupId, versionTag) {
    if (!confirm(`确定要删除线上临时文件 "${versionTag}" 吗？\n仅清理服务器上的临时备份文件，本地备份保留。`)) return;

    const serverId = AppState.selectedServer;
    const result = await apiRequest(`/api/backups/${backupId}/online`, {
        method: 'DELETE',
        body: { server_id: serverId }
    });
    if (result && result.success) {
        alert('线上临时文件已清理');
        loadBackupHistory();
    } else {
        alert(result ? result.message : '删除失败');
    }
}

// ==================== WAF 部署页面 ====================
function initWAFPage() {
    const content = document.getElementById('wafContent');
    content.innerHTML = `
        <div class="waf-selector">
            <div class="form-group">
                <label>选择服务器</label>
                <select id="wafServerSelect">
                    <option value="">-- 请选择服务器 --</option>
                    ${AppState.servers.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.host)})</option>`).join('')}
                </select>
            </div>
        </div>
        <div id="wafServerContent" style="display:none;">
            <div class="backup-tabs" style="margin-bottom:1rem;">
                <button class="monitor-tab-btn active" data-wtab="deploy" onclick="switchWAFTab('deploy')">一键部署</button>
                <button class="monitor-tab-btn" data-wtab="status" onclick="switchWAFTab('status')">部署状态</button>
            </div>

            <!-- 一键部署 -->
            <div id="wafDeployPanel">
                <div class="card">
                    <div class="card-header">
                        <span class="card-title">选择 WAF</span>
                    </div>
                    <div id="wafListContainer">
                        <p class="placeholder-text">加载中...</p>
                    </div>
                </div>
                <div class="card" style="margin-top:0.75rem;" id="wafDeployPanel" style="display:none;">
                    <div class="card-header">
                        <span class="card-title">部署配置</span>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>选中 WAF</label>
                            <input type="text" id="wafSelectedName" readonly style="background:var(--bg-secondary);">
                        </div>
                        <div class="form-group" id="wafPasswordGroup" style="display:none;">
                            <label>管理密码</label>
                            <input type="text" id="wafPassword" placeholder="WAF面板登录密码">
                        </div>
                        <div class="form-group" id="wafKeyGroup" style="display:none;">
                            <label>面板Key</label>
                            <input type="text" id="wafKey" placeholder="面板入口校验值">
                        </div>
                        <div class="form-group" style="display:flex;align-items:flex-end;">
                            <button class="btn btn-primary" id="wafDeployBtn" onclick="doWAFDeploy()">一键部署</button>
                        </div>
                    </div>
                    <div id="wafDeployResult" style="margin-top:1rem;"></div>
                </div>
            </div>

            <!-- 部署状态 -->
            <div id="wafStatusPanel" style="display:none;">
                <div class="card">
                    <div class="card-header">
                        <span class="card-title">WAF 部署状态</span>
                    </div>
                    <div style="display:flex;gap:0.75rem;margin-bottom:1rem;">
                        <button class="btn btn-secondary" onclick="checkWAFStatus()">检查状态</button>
                        <button class="btn btn-danger" onclick="doWAFUndeploy()">一键卸载</button>
                    </div>
                    <div id="wafStatusResult"></div>
                </div>
            </div>
        </div>
    `;

    // 服务器选择事件
    document.getElementById('wafServerSelect').onchange = function() {
        const serverId = this.value;
        const content = document.getElementById('wafServerContent');
        if (!serverId) {
            content.style.display = 'none';
            return;
        }
        content.style.display = 'block';
        loadWAFList();
    };

    // 加载WAF列表
    loadWAFList();
}

function switchWAFTab(tab) {
    document.querySelectorAll('#wafServerContent .monitor-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.wtab === tab);
    });
    document.getElementById('wafDeployPanel').style.display = tab === 'deploy' ? 'block' : 'none';
    document.getElementById('wafStatusPanel').style.display = tab === 'status' ? 'block' : 'none';
}

async function loadWAFList() {
    const container = document.getElementById('wafListContainer');
    if (!container) return;

    try {
        const result = await apiRequest('/api/wafs');
        if (!result || !result.success) {
            container.innerHTML = '<p class="placeholder-text">获取WAF列表失败</p>';
            return;
        }

        const wafs = result.data || [];
        if (wafs.length === 0) {
            container.innerHTML = '<p class="placeholder-text">暂无可用WAF，请在 waf/ 目录下添加WAF包</p>';
            return;
        }

        container.innerHTML = `
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>名称</th>
                            <th>描述</th>
                            <th>版本</th>
                            <th>包含文件</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${wafs.map(w => `
                            <tr>
                                <td><strong>${escapeHtml(w.name)}</strong></td>
                                <td style="max-width:300px;word-break:break-all;">${escapeHtml(w.description || '-')}</td>
                                <td>${escapeHtml(w.version || '-')}</td>
                                <td style="font-size:0.8rem;">${w.files.length > 0 ? w.files.map(f => escapeHtml(f)).join(', ') : '-'}</td>
                                <td>
                                    <button class="btn btn-sm btn-primary" onclick="selectWAF('${escapeHtml(w.name)}', ${w.has_config})">选择</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    } catch (e) {
        container.innerHTML = '<p class="placeholder-text">获取WAF列表失败</p>';
    }
}

function selectWAF(name, hasConfig) {
    document.getElementById('wafSelectedName').value = name;
    document.getElementById('wafDeployPanel').style.display = 'block';
    const pwdGroup = document.getElementById('wafPasswordGroup');
    const keyGroup = document.getElementById('wafKeyGroup');
    if (pwdGroup) pwdGroup.style.display = hasConfig ? 'block' : 'none';
    if (keyGroup) keyGroup.style.display = hasConfig ? 'block' : 'none';
}

async function doWAFDeploy() {
    const serverId = document.getElementById('wafServerSelect').value;
    if (!serverId) { alert('请先选择服务器'); return; }

    const wafName = document.getElementById('wafSelectedName').value.trim();
    if (!wafName) { alert('请先选择WAF'); return; }

    const password = document.getElementById('wafPassword') ? document.getElementById('wafPassword').value.trim() : '';
    const key = document.getElementById('wafKey') ? document.getElementById('wafKey').value.trim() : '';

    const btn = document.getElementById('wafDeployBtn');
    btn.disabled = true;
    btn.textContent = '部署中...';

    const resultDiv = document.getElementById('wafDeployResult');
    resultDiv.innerHTML = '<p style="color:var(--accent-blue);">正在部署，请稍候...</p>';

    const result = await apiRequest(`/api/servers/${serverId}/waf/deploy`, {
        method: 'POST',
        body: { waf_name: wafName, password: password, key: key }
    });

    btn.disabled = false;
    btn.textContent = '一键部署';

    if (result && result.success) {
        resultDiv.innerHTML = `
            <div style="color:var(--accent-green);margin-bottom:0.5rem;">
                <strong>${escapeHtml(result.message)}</strong>
            </div>
            ${result.data && result.data.detail ? `<pre style="background:var(--bg-secondary);padding:0.75rem;border-radius:var(--radius-sm);font-size:0.8rem;max-height:200px;overflow:auto;color:var(--text-secondary);">${escapeHtml(result.data.detail)}</pre>` : ''}
        `;
    } else {
        resultDiv.innerHTML = `<p style="color:var(--accent-red);">部署失败: ${escapeHtml(result ? result.message : '未知错误')}</p>`;
    }
}

async function doWAFUndeploy() {
    const serverId = document.getElementById('wafServerSelect').value;
    if (!serverId) { alert('请先选择服务器'); return; }

    if (!confirm('确定要卸载WAF吗？\n将执行以下操作：\n1. 终止 inotifywait 守护进程\n2. 删除 WAF 隐藏目录\n3. 删除 .user.ini / .htaccess\n4. 清理临时文件\n5. 尝试恢复被注入的PHP文件')) return;

    const resultDiv = document.getElementById('wafStatusResult');
    resultDiv.innerHTML = '<p style="color:var(--accent-blue);">正在卸载...</p>';

    const result = await apiRequest(`/api/servers/${serverId}/waf/undeploy`, { method: 'POST' });
    if (result && result.success) {
        let stepsHtml = '';
        if (result.steps && result.steps.length > 0) {
            stepsHtml = `<ul style="margin-top:0.5rem;padding-left:1.2rem;color:var(--text-secondary);font-size:0.85rem;">
                ${result.steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
            </ul>`;
        }
        resultDiv.innerHTML = `
            <div style="color:var(--accent-green);margin-bottom:0.5rem;">
                <strong>${escapeHtml(result.message)}</strong>
            </div>
            ${stepsHtml}
        `;
    } else {
        resultDiv.innerHTML = `<p style="color:var(--accent-red);">${result ? result.message : '操作失败'}</p>`;
    }
}

async function checkWAFStatus() {
    const serverId = document.getElementById('wafServerSelect').value;
    if (!serverId) { alert('请先选择服务器'); return; }

    const resultDiv = document.getElementById('wafStatusResult');
    resultDiv.innerHTML = '<p style="color:var(--accent-blue);">检查中...</p>';

    const result = await apiRequest(`/api/servers/${serverId}/waf/status`);
    if (result && result.success) {
        const d = result.data;
        resultDiv.innerHTML = `
            <div class="server-info-grid" style="margin-top:0.5rem;">
                <div class="server-info-item">
                    <span class="label">WAF状态:</span>
                    <span class="value" style="color:${d.is_deployed ? 'var(--accent-green)' : 'var(--accent-red)'};">${d.is_deployed ? '已部署' : '未部署'}</span>
                </div>
                <div class="server-info-item" style="grid-column:span 2;">
                    <span class="label">.user.ini:</span>
                    <span class="value">${escapeHtml(d.ini_content)}</span>
                </div>
            </div>
        `;
    } else {
        resultDiv.innerHTML = `<p style="color:var(--accent-red);">${result ? result.message : '检查失败'}</p>`;
    }
}

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
    }
    return `${size.toFixed(1)} ${units[i]}`;
}
