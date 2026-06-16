/**
 * WebSocket 客户端 - 实时告警推送
 */

let socket = null;
let reconnectTimer = null;
let alarmEnabled = true;

function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/socket.io/?EIO=4&transport=websocket`;

    try {
        socket = new WebSocket(url);

        socket.onopen = function() {
            console.log('[WebSocket] 已连接');
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        socket.onmessage = function(event) {
            if (event.data === '2' || event.data === '3') return; // ping/pong

            try {
                const data = JSON.parse(event.data);
                if (data.type === 'alert') {
                    handleAlert(data.data);
                } else if (data.type === 'probe_progress') {
                    handleProbeProgress(data.data);
                }
            } catch (e) {
                // 非 JSON 消息，忽略
            }
        };

        socket.onclose = function() {
            console.log('[WebSocket] 连接断开，5秒后重连');
            reconnectTimer = setTimeout(initWebSocket, 5000);
        };

        socket.onerror = function() {
            socket.close();
        };
    } catch (e) {
        console.error('[WebSocket] 初始化失败:', e);
        reconnectTimer = setTimeout(initWebSocket, 5000);
    }
}

function handleAlert(alert) {
    // 更新未读计数
    AppState.unreadAlerts++;
    updateAlertBadge();

    // 更新状态栏
    document.getElementById('statusAlerts').textContent = `未读告警: ${AppState.unreadAlerts}`;

    // 播放告警音效
    if (alarmEnabled && alert.severity === 'critical') {
        playAlarmSound();
    }

    // 如果在监控告警页面，添加到告警列表
    if (AppState.currentTab === 'monitor') {
        addAlertToPanel(alert);
    }

    // 创建浏览器通知
    if (Notification.permission === 'granted') {
        new Notification(`AWD 告警 [${getSeverityText(alert.severity)}]`, {
            body: alert.message,
            icon: '/static/favicon.ico'
        });
    }
}

function handleProbeProgress(progress) {
    // 更新探测进度
    if (AppState.currentTab === 'probe') {
        updateProbeProgress(progress);
    }
}

function updateAlertBadge() {
    const badge = document.getElementById('alertBadge');
    if (badge) {
        badge.textContent = AppState.unreadAlerts;
        badge.classList.toggle('hidden', AppState.unreadAlerts === 0);
    }
}

function addAlertToPanel(alert) {
    const container = document.getElementById('alertList');
    if (!container) return;

    const alertHtml = `
        <div class="alert-item ${alert.severity} unread fade-in">
            <span class="alert-icon">${alert.severity === 'critical' ? '🔴' : alert.severity === 'warning' ? '🟡' : '🔵'}</span>
            <div class="alert-content">
                <div class="alert-title">${escapeHtml(alert.message)}</div>
                <div class="alert-desc">${alert.server_name || ''} | ${alert.type || ''}</div>
            </div>
            <span class="alert-time">${new Date(alert.timestamp).toLocaleTimeString()}</span>
        </div>
    `;

    container.insertAdjacentHTML('afterbegin', alertHtml);
}

// 请求通知权限
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
}

// 页面加载后初始化 WebSocket
document.addEventListener('DOMContentLoaded', initWebSocket);
