# AWD 防御运维工作台

面向 AWD (Attack With Defense) 网络攻防对抗比赛的防御自动化工作台。将服务器管理、备份恢复、WAF 部署、文件/进程/流量监控、资源探测整合到一个可视化 Web 界面中，实现一键式防御操作和实时告警。

## 功能概览

### 1. 资源管理

- **服务器管理**：新增、编辑、删除多台主机，通过 SSH (paramiko) 连接并接管 Linux 主机，区分己方主机和夺取主机
- **服务器信息采集**：连接后自动采集 12 类详细信息——网络配置、系统信息、Web 服务、数据库、缓存/Redis、用户安全、定时任务、可写目录、Flag 信息、端口与进程详情、安全加固、环境/容器信息
- **分步连接进度**：前端展示分步连接进度（SSH 连接 → 基础信息 → Web 根目录检查 → MySQL 检查 → 完成）
- **资源探测**：支持 IP 范围、CIDR 网段、域名格式，50 线程并发 HTTP/HTTPS 探测，支持白名单排除，实时显示进度和结果

### 2. 基线运维

- **网站备份与恢复**：远程 tar 打包 + SFTP 下载，自定义版本标签；恢复时优先使用远端已有 tar 包（校验大小与完整性），权限自动修复（识别 www-data/apache/nginx 用户，755 目录/644 文件/755 脚本）
- **数据库备份与恢复**：通过 SSH 执行 `mysqldump`/`mysql` 命令，支持全库或单库备份，自定义版本标签，临时文件自动清理
- **WAF 一键部署**：基于包管理的 WAF 部署系统，内置 iWAF（PhoenixWAF v3.0.0）；一键部署/卸载/状态检查，卸载时深度清理（终止监控进程、删除隐藏目录、还原 `.user.ini`/`.htaccess`/`common.inc.php`、清除 PHP 注入代码）

### 3. 监测告警

- **文件基线监测**：基于 MD5 哈希比对实时检查文件变化，检测新增/修改/删除文件，触发 WebSocket 实时告警并播放告警音效
- **进程监测**：检测可疑进程（不死马、反弹 shell 等），支持自动 kill 异常进程
- **流量监控**：通过 SSH `tail -F` 实时追踪 Apache/Nginx 访问日志（支持 Apache Combined、Nginx 默认、简单格式解析），支持自定义正则匹配规则（增删改查 + 启用/禁用），预置 5 条规则模板

### 4. 安全认证

- 强密码策略（至少 12 位，含大小写字母、数字、特殊字符）
- 连续 5 次登录失败自动锁定 5 分钟
- 密码哈希存储（pbkdf2:sha256），所有 API 路由强制登录保护

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 后端框架 | Flask 3.0 + Flask-SocketIO 5.3（threading 异步模式） |
| SSH 管理 | paramiko（连接池 + 自动重连 + 指数退避） |
| 数据库 | SQLite（零配置，单机部署，8 张表） |
| 实时通信 | WebSocket（Flask-SocketIO） |
| HTTP 探测 | requests 2.32 |
| 前端 | HTML + CSS + JavaScript（单页面应用，无框架） |
| 主题 | 深色军事防御风格（蓝黑背景 + 蓝绿辉光） |
| 包管理 | uv（pyproject.toml + uv.lock） |

## 快速开始

### 环境要求

- Python 3.11+
- 目标服务器为 Linux 系统，支持 SSH 连接

### 安装与启动

```bash
# 1. 克隆项目
cd awd

# 2. 安装依赖（二选一）
# 使用 pip
pip install -r requirements.txt

# 使用 uv（推荐）
uv sync

# 3. 设置管理员密码（强密码：至少12位，含大小写字母、数字、特殊字符）
# Windows PowerShell
$env:AWD_ADMIN_PASS='YourStrong@Pass2026!'

# Linux / macOS
export AWD_ADMIN_PASS='YourStrong@Pass2026!'

# 4. 启动应用
python app.py
```

访问 `http://localhost:5000`，使用 `admin` / 你设置的密码登录。

### 环境变量配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AWD_ADMIN_USER` | 管理员用户名 | `admin` |
| `AWD_ADMIN_PASS` | 管理员初始密码 | （空，需设置） |
| `AWD_SECRET_KEY` | Flask Session 密钥 | 自动生成 |
| `AWD_HOST` | 监听地址 | `0.0.0.0` |
| `AWD_PORT` | 监听端口 | `5000` |
| `AWD_DEBUG` | 调试模式 | `False` |

## 项目结构

```
awd/
├── app.py                      # Flask 应用入口，初始化 SocketIO / 数据库 / 默认用户
├── config.py                   # 全局配置（环境变量加载 + 各模块默认值）
├── pyproject.toml              # uv 项目元数据与依赖声明
├── requirements.txt            # pip 依赖（锁定版本）
├── .python-version             # Python 版本锁定（3.11）
├── database/
│   ├── db.py                   # SQLite 连接管理，建表初始化
│   └── models.py               # 数据模型（User / Server / Backup / Alert 等 8 张表）
├── services/
│   ├── ssh_manager.py          # SSH 连接池管理（单例 + 线程安全 + 自动重连）
│   ├── server_info.py          # 远程服务器信息采集（12 类信息 + 白名单校验）
│   ├── backup.py               # 网站备份恢复（远程优先 + 完整性校验 + 权限修复）
│   ├── database_backup.py      # 数据库备份恢复（mysqldump / mysql CLI）
│   ├── waf_deploy.py           # WAF 包管理（部署 / 卸载 / 深度清理 / 状态检查）
│   ├── file_monitor.py         # 文件完整性监控（MD5 基线比对 + WebSocket 告警）
│   ├── process_monitor.py      # 进程监控（正则匹配 + 自动 kill）
│   ├── traffic_monitor.py      # 流量监控（tail -F + 多格式日志解析 + 规则匹配）
│   └── resource_probe.py       # 资源探测（50 线程并发 HTTP/HTTPS 扫描）
├── routes/
│   ├── __init__.py             # 蓝图注册（5 个 Blueprint）
│   ├── auth_routes.py          # 登录认证 API（/api/auth）
│   ├── server_routes.py        # 服务器管理 API（/api/servers）
│   ├── backup_routes.py        # 备份恢复 + WAF API（/api）
│   ├── monitor_routes.py       # 监控 + 流量规则 API（/api）
│   └── probe_routes.py         # 资源探测 API（/api/probe）
├── static/
│   ├── css/style.css           # 深色军事主题样式
│   └── js/
│       ├── app.js              # SPA 主逻辑（服务器管理 + 详情模态框 13 标签页）
│       ├── websocket.js        # WebSocket 实时告警（断线重连 + 浏览器通知）
│       ├── backup.js           # 备份恢复 + WAF 部署前端
│       ├── monitor.js          # 监控面板前端（文件 / 进程 / 告警）
│       └── probe.js            # 资源探测前端
├── templates/
│   ├── login.html              # 登录页面
│   └── index.html              # 主界面（5 标签页 SPA）
├── waf/
│   └── iWaf/                   # 内置 iWAF（PhoenixWAF v3.0.0）WAF 包
│       ├── config.json         # 包元数据（名称 / 版本 / 部署参数）
│       ├── deploy.sh           # 部署脚本
│       ├── waf.php             # WAF 核心（12 类规则 + 多层解码 + 管理面板）
│       └── waf_x86_64.so      # LD_PRELOAD 系统调用 Hook 库
├── backups/                    # 本地备份存储（web/ + database/ 子目录）
└── uploads/                    # WAF 上传临时目录
```

## 使用指南

### 服务器管理

1. 点击「新增服务器」填写 IP、端口、用户名、密码、类型（己方/夺取）
2. 点击「连接」自动采集服务器信息，前端展示分步进度
3. 点击「详情」查看完整信息（13 个标签页：基本信息、网络、系统、Web 服务、数据库、缓存、用户安全、定时任务、可写目录、Flag、端口/进程、安全加固、环境容器）

### 备份恢复

1. 在「备份恢复」标签页选择目标服务器
2. 输入版本标签（如 `初始备份`、`修复后`），点击「一键备份」
3. 在备份历史中选择版本，点击「恢复」即可一键还原
4. 恢复时系统优先使用远端已有 tar 包，校验大小和完整性，自动修复文件权限

### WAF 部署

1. 在「WAF 部署」标签页选择目标服务器
2. 从内置 WAF 包列表中选择（当前内置 iWAF），填写部署参数（密码、密钥）
3. 点击「一键部署」，系统自动：打包上传 → 运行部署脚本 → 配置 `.user.ini` → 设置只读权限
4. 可随时点击「检查状态」验证部署情况，或「一键卸载」深度清理

### 文件监控

1. 在「监控告警」标签页选择服务器，点击「建立基线」
2. 点击「启动文件监控」，系统按配置间隔自动检测文件变化
3. 检测到新增/修改/删除文件时，实时推送 WebSocket 告警并播放告警音效

### 进程监控

1. 切换到「进程监控」子标签页，选择服务器
2. 点击「启动进程监控」，系统自动检测不死马、反弹 shell 等可疑进程
3. 勾选「检测到异常自动杀进程」可启用自动处置

### 流量监控

1. 切换到「流量监控」子标签页
2. 系统预置了 5 条常见规则（Flag 读取、SQL 注入、命令执行、目录穿越、Webshell 访问）
3. 可通过「新增规则」添加自定义正则匹配规则（支持规则级启用/禁用、编辑、删除）
4. 启动监控后，通过 SSH `tail -F` 实时追踪访问日志，匹配到规则的请求实时告警

### 资源探测

1. 在「资源探测」标签页输入目标（支持 IP 范围、CIDR、域名，每行一个）
2. 配置白名单排除本机、裁判机等
3. 点击「开始探测」，系统 50 线程并发扫描，实时显示进度和结果（IP、端口、状态码、标题、响应时间）

## 预置流量监控规则

| 规则名称 | 正则表达式 | 级别 |
|----------|-----------|------|
| Flag 读取检测 | `(?i)(flag\|getflag\|readflag\|cat /flag)` | 严重 |
| SQL 注入检测 | `(?i)(union\s+select\|information_schema\|into\s+outfile\|load_file)` | 严重 |
| 命令执行检测 | `(?i)(system\s*\(\|exec\s*\(\|passthru\s*\(\|shell_exec\s*\(\|eval\s*\()` | 严重 |
| 目录穿越检测 | `(\.\./\|\.\.\\\|%2e%2e%2f\|%252e%252e%252f)` | 警告 |
| Webshell 访问检测 | `(?i)(shell\.php\|cmd\.php\|c99\.php\|r57\.php\|backdoor\|webshell)` | 严重 |

## 内置 WAF：iWAF（PhoenixWAF v3.0.0）

内置的 iWAF 是专为 AWD 比赛设计的 PHP WAF，提供 10 层防御：

| 防御层 | 说明 |
|--------|------|
| 多层解码反绕过 | URL / 双重 URL / HTML 实体 / 十六进制 / 八进制 / Unicode / Base64 / 全角 / Null 字节 / ROT13 / Gzip 解码 |
| 响应劫持 | 替换真实 Flag 为伪造 Flag，支持明文 / Base64 / 十六进制编码格式 |
| 上传检测 | 拦截恶意文件上传 |
| IP 限速与自动封禁 | 请求频率过高自动拉黑 |
| 蜜罐路径 | 伪造路径投放假 Flag |
| inotifywait 内核级文件监控 | 实时检测文件篡改 |
| SHA256 完整性基线 | 文件哈希比对 |
| 裁判机 IP 自动白名单 | 避免误封裁判流量 |
| WAF 自愈 | 检测到自身被篡改后自动恢复 |
| 隐身模式 | 伪装响应，模拟正常应用返回 |

此外还支持：LD_PRELOAD 系统调用 Hook（阻止 `execve`/`unlink`/`rename`/`chmod`）、流量重放至其他队伍、盲打转发（自动将攻击流量转发所有队伍）、自动 Flag 提交。

## 安全说明

- 所有 SSH 密码存储在本地 SQLite 数据库中，建议仅在可信网络环境使用
- 首次启动时通过环境变量 `AWD_ADMIN_PASS` 设置管理员密码，避免硬编码
- WAF 部署后 `.user.ini` 和 WAF 文件均设为 444 只读权限，防止对手篡改
- 卸载 WAF 时执行深度清理：终止监控进程、还原所有被修改的配置文件、清除 PHP 注入代码
- 文件监控完全通过 SSH 远程执行，无需在靶机上安装额外软件
- 备份恢复使用白名单正则校验版本标签，防止 Shell 注入

## 依赖清单

```
Flask==3.0.3
Flask-SocketIO==5.3.6
paramiko==3.4.1
requests==2.32.3
werkzeug==3.0.3
```

## License

MIT
