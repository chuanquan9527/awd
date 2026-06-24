# AWD 防御运维工作台

AWD 防御运维工作台是一个面向 Attack With Defense 比赛场景的 Web 控制台。项目通过 SSH 连接靶机或己方服务器，把服务器资产登记、信息采集、网站与数据库备份恢复、WAF 部署、文件完整性监控、进程异常监控和告警推送整合到一个单页界面中。

> 适用边界：本项目默认在可信内网或比赛环境中使用。服务器 SSH 密码、数据库密码和备份记录会保存在本地 SQLite 数据库中，请不要直接暴露到公网。

## 功能概览

### 服务器管理

- 支持登记多台 Linux 服务器，字段包括名称、IP、SSH 端口、SSH 用户、SSH 密码、服务器类型、Web 根目录、数据库名与数据库账号。
- 使用 `paramiko` 进行 SSH 连接测试、连接复用、命令执行、SFTP 上传和下载。
- 连接后自动采集服务器信息，包括内核、PHP、MySQL、开放端口、进程、可疑用户、SUID/SGID 文件、网络、系统、Web 服务、数据库、Redis、定时任务、可写目录、Flag 探测、容器与资源信息等。
- 前端提供分步连接状态：SSH 连接、基础信息采集、Web 根目录检查、MySQL 连接检查、信息保存。
- 支持通过 Web 控制台修改远程 SSH 用户密码和 MySQL 用户密码，密码强度要求与系统登录密码保持一致。

### 备份与恢复

- 网站备份：在远程服务器上将 `web_root` 打包为 tar，通过 SFTP 下载到本地 `backups/web/`，并可保留远程临时备份以加速恢复。
- 网站恢复：优先使用备份记录中的远程 tar；远程文件不存在时回退到本地备份上传。恢复前会清空 Web 根目录，解包后自动修复常见 Web 用户权限。
- 数据库备份：通过远程 `mysqldump` 生成 SQL 文件，支持全库或单库备份，下载到本地 `backups/database/`。
- 数据库恢复：优先使用远程 SQL 备份；否则上传本地 SQL 后执行 `mysql` 导入。
- 备份版本标签做白名单校验，仅允许字母、数字、点、下划线和短横线，降低命令注入风险。
- 支持删除本地备份记录和清理远程临时备份文件。

### WAF 部署

- WAF 包以目录形式放在 `waf/` 下，每个包至少需要 `deploy.sh`，可选 `config.json` 描述版本、说明和部署参数。
- 工作台会将选定 WAF 包打包上传到目标服务器，在临时目录解压并执行 `deploy.sh <web_root> [extra_args]`。
- 当前可被工作台直接识别和部署的内置包是 `iWaf`。`waf/watchbird/` 中保留了 Watchbird WAF 资产和说明，但它缺少当前部署管理器要求的 `deploy.sh`，补齐后才会出现在 WAF 列表中。
- 提供 WAF 状态检查和卸载入口。卸载逻辑会清理 `.user.ini`、隐藏目录、WAF watcher、临时文件，并尝试移除 PHP 文件中的注入行。

### 脚本部署

- 支持维护 PHP 或 Shell 类型的部署脚本，字段包括脚本名称、类型、描述、远程脚本目录、包含文件和部署 Shell 代码。
- 支持多文件上传、追加和移除；脚本删除时会同步删除本地包含文件和部署脚本。
- 新增和编辑时可选择当前控制服务器的可写目录，默认 `/tmp`，也支持手动输入远程绝对路径。
- 部署时会把包含文件和 `deploy.sh` 打包上传到脚本目录下的临时子目录，执行 `bash deploy.sh <web_root> <remote_extract_dir>`，并展示 stdout、stderr 和退出码。

### 监控与告警

- 文件监控：为一个或多个目录建立 MD5 基线，支持每个目录配置正则白名单。监控时检测新增、修改和删除文件。
- 进程监控：定期读取 `ps aux`，匹配配置中的可疑正则，例如反弹 shell、不死马、socket 脚本、crontab 等。
- 自动处置：进程监控可选择检测到异常后自动 `kill -9`。
- 告警记录：告警写入 SQLite，可标记已读、批量删除或全部清空。
- 实时推送：使用 Flask-SocketIO 推送告警到前端，支持浏览器通知和告警音效。

### 登录认证

- 首次启动时通过环境变量创建管理员账号。
- 登录密码必须至少 12 位，且包含大写字母、小写字母、数字和特殊字符。
- 连续 5 次登录失败会锁定账号 5 分钟。
- 登录状态基于 Flask Session；业务 API 使用 `login_required` 保护。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.11+, Flask, Flask-SocketIO |
| SSH/SFTP | paramiko |
| 数据库 | SQLite |
| 前端 | HTML, CSS, 原生 JavaScript 单页应用 |
| 实时通信 | Socket.IO |
| 依赖管理 | `requirements.txt` 或 `uv` / `pyproject.toml` |

## 快速开始

### 环境要求

- Python 3.11+
- 可访问目标 Linux 服务器的 SSH 网络
- 目标服务器按需安装 `tar`、`find`、`md5sum`、`ps`、`mysql`、`mysqldump`、`php` 等常见命令
- 浏览器能访问 Socket.IO 客户端 CDN：`https://cdn.socket.io/4.5.4/socket.io.min.js`

### 安装依赖

```bash
# 使用 pip
pip install -r requirements.txt

# 或使用 uv
uv sync
```

### 配置管理员账号

首次启动前必须设置 `AWD_ADMIN_PASS`，否则不会创建默认管理员。

Windows PowerShell:

```powershell
$env:AWD_ADMIN_USER='admin'
$env:AWD_ADMIN_PASS='YourStrong@Pass2026!'
$env:AWD_SECRET_KEY='replace-with-a-random-secret'
```

Linux / macOS:

```bash
export AWD_ADMIN_USER='admin'
export AWD_ADMIN_PASS='YourStrong@Pass2026!'
export AWD_SECRET_KEY='replace-with-a-random-secret'
```

### 启动应用

```bash
python app.py
```

默认监听 `0.0.0.0:5000`。本机访问：

```text
http://localhost:5000
```

登录后先在「服务器管理」中新增服务器并点击「连接」，随后「备份恢复」「WAF部署」「监控告警」会默认操作当前在线控制服务器。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AWD_ADMIN_USER` | `admin` | 首次初始化管理员用户名 |
| `AWD_ADMIN_PASS` | 空 | 首次初始化管理员密码，必须符合强密码策略 |
| `AWD_SECRET_KEY` | `awd-defense-workbench-secret-key-2026` | Flask Session 密钥，生产或比赛环境建议显式覆盖 |
| `AWD_HOST` | `0.0.0.0` | Flask-SocketIO 监听地址 |
| `AWD_PORT` | `5000` | Flask-SocketIO 监听端口 |
| `AWD_DEBUG` | `False` | 是否启用调试模式 |

## 项目结构

```text
awd/
├── app.py                    # Flask 应用入口，初始化 SocketIO、蓝图、数据库和默认管理员
├── config.py                 # 全局配置、环境变量、密码策略、SSH/备份/WAF/监控默认值
├── requirements.txt          # pip 依赖版本
├── pyproject.toml            # uv 项目配置
├── database/
│   ├── db.py                 # SQLite 建表和数据库访问工具
│   └── models.py             # User、Server、Backup、Alert、MonitorConfig 数据模型
├── routes/
│   ├── auth_routes.py        # 登录、登出、认证检查、修改登录密码
│   ├── server_routes.py      # 服务器 CRUD、连接采集、可写目录探测、远程密码修改
│   ├── backup_routes.py      # 网站/数据库备份恢复、WAF 列表/部署/卸载/状态
│   └── monitor_routes.py     # 文件基线、监控启停、进程列表、告警管理
├── services/
│   ├── ssh_manager.py        # SSH 连接单例、命令执行、SFTP 上传下载
│   ├── server_info.py        # 服务器基础与详细信息采集
│   ├── backup.py             # 网站备份与恢复
│   ├── database_backup.py    # MySQL 备份与恢复
│   ├── waf_deploy.py         # 本地 WAF 包管理与远程部署/卸载
│   ├── script_deploy.py      # 脚本部署包管理、文件上传和远程执行
│   ├── file_monitor.py       # 文件 MD5 基线监控和告警推送
│   └── process_monitor.py    # 可疑进程检测、自动 kill 和告警推送
├── templates/
│   ├── login.html            # 登录页
│   └── index.html            # 主控制台页面
├── static/
│   ├── css/style.css         # 控制台样式
│   ├── js/app.js             # 主应用逻辑、服务器管理、认证状态
│   ├── js/backup.js          # 备份恢复和 WAF 页面逻辑
│   ├── js/scripts.js         # 脚本部署页面逻辑
│   ├── js/monitor.js         # 文件/进程监控和告警列表逻辑
│   ├── js/websocket.js       # Socket.IO 告警客户端
│   └── audio/alarm.wav       # 告警音效
├── waf/
│   ├── iWaf/                 # 内置 iWAF 部署包，包含 deploy.sh 和 config.json
│   └── watchbird/            # Watchbird WAF 资产；补齐 deploy.sh 后可接入部署列表
├── backups/                  # 运行时生成，本地网站/数据库备份目录
├── scripts/                  # 运行时生成，本地脚本部署包目录
├── uploads/                  # WAF 上传或临时文件目录
└── logs/                     # 运行日志目录
```

## 数据库与本地文件

应用启动时会自动创建 `database/awd.db`，主要表如下：

- `users`：控制台用户、密码哈希、登录失败次数、锁定时间。
- `servers`：服务器连接信息、Web/数据库配置、采集结果和在线状态。
- `backups`：网站或数据库备份记录、本地路径、远程临时路径和文件大小。
- `file_baselines`：文件路径与 MD5 基线。
- `alerts`：文件变更或进程异常告警。
- `monitor_config`：监控开关、间隔、目录、白名单和自动 kill 配置。
- `deployment_scripts`：脚本部署元数据、脚本目录、部署 Shell 代码和包含文件列表。

运行过程中会写入：

- `backups/web/`：网站 tar 备份。
- `backups/database/`：数据库 SQL 备份。
- `scripts/`：脚本部署模块上传的包含文件和部署脚本。
- `database/awd.db`：SQLite 数据库。

这些运行时数据通常不应提交到 Git。

## 常用工作流

### 1. 登记并连接服务器

1. 打开「服务器管理」，点击「新增服务器」。
2. 填写 SSH 信息、Web 根目录和可选数据库信息。
3. 保存后点击「连接」，等待采集流程完成。
4. 在线服务器会进入底部「当前控制服务器」候选列表，后续备份、WAF、监控默认操作该服务器。

### 2. 备份与恢复网站

1. 进入「备份恢复」，选择「网站备份」。
2. 输入版本标签，例如 `init`、`after_fix_1`。
3. 选择远程临时存储目录，点击「一键备份」。
4. 在备份历史中点击「恢复」即可回滚到指定版本。

注意：网站恢复会清空当前 Web 根目录，然后解包备份内容。执行前请确认目标服务器和版本标签无误。

### 3. 备份与恢复数据库

1. 进入「备份恢复」，切换到「数据库备份」。
2. 选择数据库名；留空表示全库备份。
3. 输入版本标签并执行备份。
4. 在备份历史中恢复指定 SQL 版本。

目标服务器需要可执行 `mysql` 和 `mysqldump`，且服务器配置中的数据库账号必须有相应权限。

### 4. 部署 WAF

1. 进入「WAF部署」。
2. 在 WAF 列表中选择 `iWaf` 或自定义部署包。
3. 若包声明了部署参数，填写管理密码、入口 key 等参数。
4. 点击「一键部署」。
5. 在「部署状态」中检查 `.user.ini` 是否包含 `auto_prepend_file`。

新增 WAF 包时，在 `waf/<name>/` 下放置 `deploy.sh`。如果需要让前端展示描述和参数，再添加 `config.json`：

```json
{
  "name": "ExampleWAF",
  "description": "示例 WAF 包",
  "version": "1.0.0",
  "deploy_args": "--password <管理密码> --key <入口Key>"
}
```

### 5. 脚本部署

1. 进入「脚本部署」。
2. 点击「新增脚本」，填写名称、类型、描述和脚本目录。
3. 上传一个或多个包含文件，并编写部署 Shell 代码。
4. 保存后在列表中点击「部署」，确认目标服务器和脚本目录。
5. 部署完成后查看远程解压目录、退出码、stdout 和 stderr。

部署脚本执行时会收到两个参数：`$1` 是目标服务器 Web 根目录，`$2` 是远程解压目录，包含文件位于 `$2/files/`。

### 6. 文件完整性监控

1. 进入「监控告警」的「文件监控」。
2. 配置一个或多个目录，每个目录可填写多行正则白名单。
3. 点击「建立基线」。
4. 打开「文件监控」开关。
5. 文件新增、修改、删除会写入告警并通过 WebSocket 推送。

### 7. 进程监控

1. 进入「监控告警」的「进程监控」。
2. 设置监控间隔，可选「检测到异常自动杀进程」。
3. 启动监控后，系统会定期匹配 `config.py` 中的 `PROCESS_MONITOR_SUSPICIOUS_PATTERNS`。
4. 也可以在进程列表中手动点击 `Kill` 终止指定 PID。

## API 概览

所有业务接口除登录、登出和登录检查外都需要登录态。

### 认证

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 登录 |
| `POST` | `/api/auth/logout` | 登出 |
| `GET` | `/api/auth/check` | 检查登录状态 |
| `PUT` | `/api/auth/password` | 修改控制台登录密码 |

### 服务器

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/servers` | 服务器列表 |
| `POST` | `/api/servers` | 新增服务器 |
| `PUT` | `/api/servers/<id>` | 更新服务器 |
| `DELETE` | `/api/servers/<id>` | 删除服务器 |
| `POST` | `/api/servers/<id>/connect` | 连接并完整采集信息 |
| `POST` | `/api/servers/<id>/connect-step` | 分步连接采集 |
| `POST` | `/api/servers/<id>/refresh` | 刷新服务器信息 |
| `GET` | `/api/servers/<id>/info` | 获取服务器详情 |
| `GET` | `/api/servers/<id>/writable-dirs` | 探测可写目录 |
| `POST` | `/api/servers/<id>/password/ssh` | 修改远程 SSH 密码 |
| `POST` | `/api/servers/<id>/password/mysql` | 修改远程 MySQL 密码 |

### 备份与 WAF

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/servers/<id>/backup/web` | 网站备份 |
| `POST` | `/api/servers/<id>/restore/web/<backup_id>` | 网站恢复 |
| `GET` | `/api/servers/<id>/databases` | 获取数据库列表 |
| `POST` | `/api/servers/<id>/backup/database` | 数据库备份 |
| `POST` | `/api/servers/<id>/restore/database/<backup_id>` | 数据库恢复 |
| `GET` | `/api/servers/<id>/backups` | 获取备份列表，可用 `type=web/database` 过滤 |
| `DELETE` | `/api/backups/<backup_id>` | 删除本地备份 |
| `DELETE` | `/api/backups/<backup_id>/online` | 删除远程临时备份 |
| `GET` | `/api/wafs` | WAF 包列表 |
| `GET` | `/api/wafs/<name>` | WAF 包详情 |
| `POST` | `/api/servers/<id>/waf/deploy` | 部署 WAF |
| `POST` | `/api/servers/<id>/waf/undeploy` | 卸载 WAF |
| `GET` | `/api/servers/<id>/waf/status` | 检查 WAF 状态 |

### 脚本部署

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/scripts` | 脚本列表 |
| `GET` | `/api/scripts/<id>` | 脚本详情 |
| `POST` | `/api/scripts` | 新增脚本，使用 `multipart/form-data` |
| `PUT` | `/api/scripts/<id>` | 更新脚本，支持追加和移除文件 |
| `DELETE` | `/api/scripts/<id>` | 删除脚本及本地文件 |
| `POST` | `/api/servers/<server_id>/scripts/<script_id>/deploy` | 部署脚本到指定服务器 |

### 监控与告警

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/servers/<id>/monitor/baseline` | 建立文件基线 |
| `POST` | `/api/servers/<id>/monitor/start` | 启动文件或进程监控 |
| `POST` | `/api/servers/<id>/monitor/stop` | 停止文件或进程监控 |
| `GET` | `/api/servers/<id>/monitor/status` | 获取监控状态 |
| `GET` | `/api/servers/<id>/processes` | 获取进程列表 |
| `POST` | `/api/servers/<id>/processes/<pid>/kill` | 终止进程 |
| `GET` | `/api/alerts` | 获取告警列表 |
| `PUT` | `/api/alerts/<id>/read` | 标记单条告警已读 |
| `PUT` | `/api/alerts/read-all` | 全部标记已读 |
| `DELETE` | `/api/alerts/<id>` | 删除单条告警 |
| `DELETE` | `/api/alerts/batch` | 批量删除告警 |
| `DELETE` | `/api/alerts/all` | 删除全部告警 |

## 安全注意事项

- 请务必覆盖默认 `AWD_SECRET_KEY`，否则 Session 签名密钥是公开固定值。
- `servers` 表会明文保存 SSH 密码和数据库密码。建议只在比赛内网或个人隔离环境使用，并限制 `database/awd.db` 文件权限。
- 网站恢复会递归清空目标 `web_root` 下的内容。代码已拒绝 `/`、`/root`、`/home` 等明显危险路径，但仍应在 UI 操作前确认目标目录。
- WAF 部署和卸载会修改目标 Web 根目录下的 `.user.ini`、`.htaccess`、PHP 文件和隐藏目录。部署前建议先做网站备份。
- 脚本部署会执行用户保存的 Shell 代码，属于远程命令执行能力，请只在可信比赛环境和已授权服务器上使用。
- 进程自动 kill 是高风险功能，建议先观察告警规则效果，再在比赛中按需开启。
- 本项目包含攻防比赛相关 WAF 包能力，请遵守比赛规则和授权边界。

## 开发提示

- 后端入口是 `app.py`，蓝图集中在 `routes/`，业务实现集中在 `services/`。
- 监控线程保存在 `routes.monitor_routes` 的单例 `FileMonitor` 和 `ProcessMonitor` 中，重启应用后线程状态不会自动恢复，需要重新启动监控。
- 前端无构建流程，页面由 Flask 模板直接加载 `static/js/*.js`。
- 脚本部署模块的详细设计文档位于 `docs/script-deploy-design.md`。
- 若要调整可疑进程规则，修改 `config.py` 中的 `PROCESS_MONITOR_SUSPICIOUS_PATTERNS`。
- 若要调整默认监控间隔、备份目录、SSH 超时时间，也在 `config.py` 中配置。

## License

MIT
