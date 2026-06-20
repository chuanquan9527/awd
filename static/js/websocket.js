/**
 * WebSocket 客户端 - 实时告警推送 (使用 Socket.IO)
 */

let socket = null;

// 使用全局变量，与 monitor.js 共享
// 默认为 true（如果 localStorage 中没有保存值）
// 注意：monitor.js 的 restoreAlarmState() 会在页面初始化后再次更新此值
if (window.alarmEnabled === undefined) {
    const savedState = localStorage.getItem('alarmEnabled');
    window.alarmEnabled = savedState === null ? true : savedState === 'true';
    console.log('[WebSocket] 初始化音效状态:', window.alarmEnabled, 'localStorage:', savedState);
}

function initWebSocket() {
    // 使用 Socket.IO 客户端连接
    try {
        socket = io({
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionDelay: 5000,
            reconnectionAttempts: Infinity
        });

        socket.on('connect', function() {
            console.log('[WebSocket] 已连接, alarmEnabled:', window.alarmEnabled);
        });

        socket.on('disconnect', function() {
            console.log('[WebSocket] 连接断开');
        });

        socket.on('alert', function(alert) {
            console.log('[WebSocket] 收到告警:', alert);
            handleAlert(alert);
        });

        socket.on('connect_error', function(error) {
            console.error('[WebSocket] 连接错误:', error);
        });

    } catch (e) {
        console.error('[WebSocket] 初始化失败:', e);
    }
}

function handleAlert(alert) {
    console.log('[WebSocket] 处理告警:', alert);
    console.log('[WebSocket] alarmEnabled:', window.alarmEnabled, 'severity:', alert.severity);
    
    // 更新未读计数
    AppState.unreadAlerts++;
    updateAlertBadge();

    // 更新状态栏
    const statusAlerts = document.getElementById('statusAlerts');
    if (statusAlerts) {
        statusAlerts.textContent = `未读告警: ${AppState.unreadAlerts}`;
    }

    // 播放告警音效（检查开关状态）
    // critical 和 warning 级别都播放音效
    if (window.alarmEnabled && (alert.severity === 'critical' || alert.severity === 'warning')) {
        console.log('[WebSocket] 播放告警音效');
        playAlarmSound();
    } else {
        console.log('[WebSocket] 音效已关闭或非critical/warning告警，跳过播放');
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