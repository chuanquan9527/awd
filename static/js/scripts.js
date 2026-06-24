/**
 * 脚本部署前端逻辑
 */

const ScriptState = {
    scripts: [],
    writableDirs: ['/tmp'],
    removedFiles: [],
    editingScript: null
};

function initScriptsPage() {
    const content = document.getElementById('scriptContent');
    if (!content) return;

    content.innerHTML = `
        <div class="panel-header">
            <h2>脚本部署</h2>
            <button class="btn btn-primary" onclick="showScriptModal(null)">
                <span>+</span> 新增脚本
            </button>
        </div>
        <div id="scriptServerHint" class="script-server-hint"></div>
        <div id="scriptListContainer">
            <p class="placeholder-text">正在加载脚本列表...</p>
        </div>
        <div id="scriptDeployResult" class="script-deploy-result" style="display:none;"></div>
    `;

    loadScripts();
}

async function loadScripts() {
    const hint = document.getElementById('scriptServerHint');
    const server = getControlServer();
    if (hint) {
        hint.innerHTML = server
            ? `当前控制服务器：<strong>${escapeHtml(server.name)}</strong> <span>${escapeHtml(server.host)}:${server.port}</span>`
            : '暂无在线控制服务器。可以管理脚本，但部署前需要先在服务器管理中连接服务器。';
    }

    const result = await apiRequest('/api/scripts');
    if (!result || !result.success) {
        const container = document.getElementById('scriptListContainer');
        if (container) container.innerHTML = '<p class="placeholder-text">脚本列表加载失败</p>';
        return;
    }
    ScriptState.scripts = result.data || [];
    renderScriptList();
}

function renderScriptList() {
    const container = document.getElementById('scriptListContainer');
    if (!container) return;

    const scripts = ScriptState.scripts || [];
    if (scripts.length === 0) {
        container.innerHTML = '<p class="placeholder-text">暂无脚本，请点击右上角“新增脚本”创建</p>';
        return;
    }

    container.innerHTML = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>脚本名称</th>
                        <th>脚本类型</th>
                        <th>脚本描述</th>
                        <th>脚本目录</th>
                        <th>包含文件</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${scripts.map(script => `
                        <tr>
                            <td><strong>${escapeHtml(script.name)}</strong></td>
                            <td>${getScriptTypeBadge(script.script_type)}</td>
                            <td class="script-desc-cell">${escapeHtml(script.description || '-')}</td>
                            <td><code>${escapeHtml(script.remote_dir || '/tmp')}</code></td>
                            <td>${renderScriptFilesSummary(script.files || [])}</td>
                            <td>
                                <button class="btn btn-sm btn-secondary" onclick="showScriptModal(${script.id})">编辑</button>
                                <button class="btn btn-sm btn-danger" onclick="deleteScript(${script.id})">删除</button>
                                <button class="btn btn-sm btn-primary" onclick="deployScript(${script.id})">部署</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function getScriptTypeBadge(type) {
    const cls = type === 'php' ? 'badge-info' : 'badge-warning';
    return `<span class="badge ${cls}">${escapeHtml(type || '-')}</span>`;
}

function renderScriptFilesSummary(files) {
    if (!files || files.length === 0) return '<span class="text-muted">无文件</span>';
    const names = files.slice(0, 3).map(f => escapeHtml(f.filename)).join(', ');
    const suffix = files.length > 3 ? ` 等 ${files.length} 个文件` : '';
    return `<span title="${files.map(f => escapeHtml(f.filename)).join('\n')}">${names}${suffix}</span>`;
}

async function loadScriptWritableDirs(currentValue) {
    const server = getControlServer();
    const dirs = ['/tmp'];
    if (server) {
        const result = await apiRequest(`/api/servers/${server.id}/writable-dirs`);
        if (result && result.success && Array.isArray(result.data)) {
            result.data.forEach(dir => {
                if (dir && !dirs.includes(dir)) dirs.push(dir);
            });
        }
    }
    if (currentValue && !dirs.includes(currentValue)) dirs.push(currentValue);
    ScriptState.writableDirs = dirs;
    renderRemoteDirOptions(currentValue || '/tmp');
}

function renderRemoteDirOptions(selected) {
    const select = document.getElementById('scriptRemoteDir');
    if (!select) return;
    const dirs = ScriptState.writableDirs || ['/tmp'];
    select.innerHTML = dirs.map(dir => `
        <option value="${escapeHtml(dir)}" ${dir === selected ? 'selected' : ''}>${escapeHtml(dir)}${dir === selected && !['/tmp', '/var/tmp', '/dev/shm', '/var/www/html', '/var/www', '/home'].includes(dir) ? '（当前值）' : ''}</option>
    `).join('') + '<option value="__custom__">手动输入...</option>';
}

function getScriptModalHtml(script) {
    const s = script || {};
    const files = s.files || [];
    const remoteDir = s.remote_dir || '/tmp';
    return `
        <div class="modal-section">
            <div class="modal-section-title">脚本信息</div>
            <div class="form-row">
                <div class="form-group">
                    <label>脚本名称 *</label>
                    <input type="text" id="scriptName" value="${escapeHtml(s.name || '')}" placeholder="如: 部署WebShell查杀脚本">
                </div>
                <div class="form-group">
                    <label>脚本类型 *</label>
                    <select id="scriptType">
                        <option value="php" ${s.script_type === 'php' ? 'selected' : ''}>php</option>
                        <option value="shell" ${s.script_type === 'shell' ? 'selected' : ''}>shell</option>
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label>脚本描述</label>
                <textarea id="scriptDescription" rows="3" placeholder="描述用途、适用场景或注意事项">${escapeHtml(s.description || '')}</textarea>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>脚本目录 *</label>
                    <select id="scriptRemoteDir" onchange="toggleScriptRemoteDirCustom(this.value)">
                        <option value="${escapeHtml(remoteDir)}">${escapeHtml(remoteDir)}</option>
                    </select>
                    <input type="text" id="scriptRemoteDirCustom" value="" placeholder="输入远程绝对路径" style="display:none;margin-top:0.4rem;">
                </div>
                <div class="form-group">
                    <label>包含文件</label>
                    <input type="file" id="scriptFiles" multiple>
                </div>
            </div>
        </div>

        <div class="modal-section">
            <div class="modal-section-title">已有文件</div>
            <div id="scriptExistingFiles" class="script-file-list">
                ${renderExistingScriptFiles(files)}
            </div>
        </div>

        <div class="modal-section">
            <div class="modal-section-title">部署脚本 *</div>
            <textarea id="scriptDeployCode" class="script-code-editor" spellcheck="false" placeholder="set -e&#10;WEB_ROOT=&quot;$1&quot;&#10;PACKAGE_DIR=&quot;$2&quot;&#10;echo deploy ok">${escapeHtml(s.deploy_script || '')}</textarea>
            <p class="script-help-text">参数约定：$1 为服务器 Web 根目录，$2 为远程解压目录，包含文件位于 $2/files/。</p>
        </div>
        <div id="scriptError" class="form-error" style="display:none;"></div>
    `;
}

function renderExistingScriptFiles(files) {
    if (!files || files.length === 0) {
        return '<p class="placeholder-text">暂无已上传文件</p>';
    }
    return files.map(file => `
        <div class="script-file-item" data-filename="${escapeHtml(file.filename)}">
            <span>${escapeHtml(file.filename)}</span>
            <small>${formatFileSize(file.size || 0)}</small>
            <button class="btn btn-sm btn-danger" onclick="markScriptFileRemoved('${escapeJs(file.filename)}')">移除</button>
        </div>
    `).join('');
}

async function showScriptModal(scriptId) {
    const script = scriptId ? ScriptState.scripts.find(s => s.id === scriptId) : null;
    ScriptState.editingScript = script || null;
    ScriptState.removedFiles = [];

    showModal(script ? '编辑脚本' : '新增脚本', getScriptModalHtml(script), [
        { text: '取消', class: 'btn-secondary', action: hideModal },
        { text: '保存', class: 'btn-primary', action: () => saveScript(script ? script.id : null) }
    ]);

    await loadScriptWritableDirs(script ? script.remote_dir : '/tmp');
}

function toggleScriptRemoteDirCustom(value) {
    const input = document.getElementById('scriptRemoteDirCustom');
    if (!input) return;
    if (value === '__custom__') {
        input.style.display = 'block';
        input.focus();
    } else {
        input.style.display = 'none';
    }
}

function markScriptFileRemoved(filename) {
    if (!ScriptState.removedFiles.includes(filename)) {
        ScriptState.removedFiles.push(filename);
    }
    const item = Array.from(document.querySelectorAll('.script-file-item'))
        .find(el => el.dataset.filename === filename);
    if (item) {
        item.classList.add('removed');
        item.querySelector('button').disabled = true;
        item.querySelector('button').textContent = '已移除';
    }
}

function getSelectedScriptRemoteDir() {
    const select = document.getElementById('scriptRemoteDir');
    if (!select) return '/tmp';
    if (select.value === '__custom__') {
        const custom = document.getElementById('scriptRemoteDirCustom');
        return custom && custom.value.trim() ? custom.value.trim() : '/tmp';
    }
    return select.value || '/tmp';
}

async function saveScript(scriptId) {
    const errorDiv = document.getElementById('scriptError');
    const name = document.getElementById('scriptName').value.trim();
    const scriptType = document.getElementById('scriptType').value;
    const description = document.getElementById('scriptDescription').value.trim();
    const remoteDir = getSelectedScriptRemoteDir();
    const deployScript = document.getElementById('scriptDeployCode').value;
    const fileInput = document.getElementById('scriptFiles');

    if (!name) {
        showScriptFormError(errorDiv, '请输入脚本名称');
        return;
    }
    if (!deployScript.trim()) {
        showScriptFormError(errorDiv, '请输入部署脚本');
        return;
    }
    if (!remoteDir.startsWith('/')) {
        showScriptFormError(errorDiv, '脚本目录必须是绝对路径');
        return;
    }

    const formData = new FormData();
    formData.append('name', name);
    formData.append('script_type', scriptType);
    formData.append('description', description);
    formData.append('remote_dir', remoteDir);
    formData.append('deploy_script', deployScript);
    formData.append('remove_files', JSON.stringify(ScriptState.removedFiles));

    Array.from(fileInput.files || []).forEach(file => {
        formData.append('files', file);
    });

    const url = scriptId ? `/api/scripts/${scriptId}` : '/api/scripts';
    const method = scriptId ? 'PUT' : 'POST';
    const result = await scriptFormRequest(url, method, formData);

    if (result && result.success) {
        hideModal();
        await loadScripts();
    } else {
        showScriptFormError(errorDiv, result ? result.message : '保存失败');
    }
}

function showScriptFormError(errorDiv, message) {
    if (!errorDiv) return;
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
}

async function scriptFormRequest(url, method, formData) {
    try {
        const response = await fetch(url, { method, body: formData });
        if (response.status === 401) {
            window.location.href = '/login';
            return null;
        }
        return await response.json();
    } catch (e) {
        return { success: false, message: '网络请求失败' };
    }
}

async function deleteScript(scriptId) {
    const script = ScriptState.scripts.find(s => s.id === scriptId);
    if (!script) return;
    if (!confirm(`确定要删除脚本 “${script.name}” 吗？\n本地包含文件和部署脚本都会被删除。`)) return;

    const result = await apiRequest(`/api/scripts/${scriptId}`, { method: 'DELETE' });
    if (result && result.success) {
        await loadScripts();
    } else {
        alert(result ? result.message : '删除失败');
    }
}

async function deployScript(scriptId) {
    const script = ScriptState.scripts.find(s => s.id === scriptId);
    const server = getControlServer();
    if (!script) return;
    if (!server) {
        alert('暂无在线控制服务器，请先在服务器管理中连接服务器');
        return;
    }

    const ok = confirm(`确定部署脚本 “${script.name}” 吗？\n目标服务器：${server.name} (${server.host})\n脚本目录：${script.remote_dir || '/tmp'}`);
    if (!ok) return;

    const resultDiv = document.getElementById('scriptDeployResult');
    if (resultDiv) {
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '<p style="color:var(--accent-blue);">正在部署，请稍候...</p>';
    }

    const result = await apiRequest(`/api/servers/${server.id}/scripts/${scriptId}/deploy`, {
        method: 'POST',
        body: {}
    });

    if (resultDiv) {
        resultDiv.innerHTML = renderDeployResult(result, script);
    }
}

function renderDeployResult(result, script) {
    if (!result) {
        return '<p style="color:var(--accent-red);">部署失败：无响应</p>';
    }
    const data = result.data || {};
    const success = result.success;
    return `
        <div class="card script-result-card">
            <div class="card-header">
                <span class="card-title">部署结果 - ${escapeHtml(script.name)}</span>
                <span class="badge ${success ? 'badge-online' : 'badge-offline'}">${success ? '成功' : '失败'}</span>
            </div>
            <div class="server-info-grid">
                <div class="server-info-item"><span class="label">脚本目录:</span><span class="value">${escapeHtml(data.remote_dir || script.remote_dir || '/tmp')}</span></div>
                <div class="server-info-item"><span class="label">远程目录:</span><span class="value">${escapeHtml(data.remote_extract_dir || '-')}</span></div>
                <div class="server-info-item"><span class="label">退出码:</span><span class="value">${data.exit_code !== undefined ? data.exit_code : '-'}</span></div>
            </div>
            <div class="script-output-block">
                <div class="detail-subtitle">stdout</div>
                <pre>${escapeHtml(data.stdout || '')}</pre>
                <div class="detail-subtitle">stderr</div>
                <pre>${escapeHtml(data.stderr || result.message || '')}</pre>
            </div>
        </div>
    `;
}

function escapeJs(text) {
    return String(text || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}
