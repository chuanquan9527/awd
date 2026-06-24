# 脚本部署模块设计文档

## 1. 目标与范围

在现有 AWD 防御运维工作台中新增「脚本部署」模块，用于维护可复用部署脚本，并将脚本包含文件上传到远程服务器的指定脚本目录后执行部署 Shell 脚本。

模块能力：

- 脚本 CRUD：新增、列表、详情、编辑、删除。
- 脚本类型：`php`、`shell`。
- 脚本目录：每个脚本保存一个远程部署目录，默认 `/tmp`；新增/编辑时优先从当前控制服务器可写目录中选择。
- 脚本文件：支持多文件上传、列表展示、移除。
- 部署脚本：保存一段 Shell 代码，部署时在远程服务器执行。
- 脚本部署：将包含文件上传到脚本目录下的临时子目录，执行部署脚本，返回 stdout/stderr/退出码。
- 前端入口：主导航新增「脚本部署」标签页，沿用当前控制服务器机制。

不做范围：

- 不实现定时部署、批量部署多服务器。
- 不实现脚本执行历史审计表，部署结果仅在本次响应和前端结果区展示。
- 不实现 Monaco/CodeMirror 等外部编辑器，先使用原生 `textarea` 模拟代码编辑器，避免引入构建流程。

## 2. 数据与存储设计

新增本地存储目录：

```text
scripts/
└── <script_id>/
    ├── files/
    │   ├── uploaded_file_1.php
    │   └── uploaded_file_2.sh
    └── deploy.sh
```

新增配置项：

```python
SCRIPT_STORAGE_DIR = os.path.join(BASE_DIR, 'scripts')
SCRIPT_DEPLOY_TIMEOUT = 180
SCRIPT_ALLOWED_TYPES = ['php', 'shell']
```

不再设置固定 `SCRIPT_REMOTE_BASE_DIR`。远程上传目录使用脚本记录中的 `remote_dir` 字段值；字段为空时兜底为 `/tmp`。

新增数据库表 `deployment_scripts`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | 脚本 ID |
| `name` | TEXT NOT NULL UNIQUE | 脚本名称 |
| `script_type` | TEXT NOT NULL | `php` 或 `shell` |
| `description` | TEXT | 脚本描述 |
| `remote_dir` | TEXT NOT NULL DEFAULT '/tmp' | 远程脚本目录 |
| `deploy_script` | TEXT NOT NULL | 部署 Shell 代码 |
| `files` | TEXT | JSON 数组，记录包含文件名、大小、相对路径 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

文件元数据 JSON 结构：

```json
[
  {
    "filename": "waf.php",
    "size": 10240,
    "relative_path": "files/waf.php"
  }
]
```

校验规则：

- `name`：必填，1-64 字符，不允许路径分隔符。
- `script_type`：只能为 `php` 或 `shell`。
- `description`：可空，最大 500 字符。
- `remote_dir`：必填，默认 `/tmp`，必须是绝对路径，不允许 `/`、`/root`。
- `deploy_script`：必填，最大 20000 字符。
- 上传文件名使用 `secure_filename` 规范化；重名文件覆盖同名旧文件。
- 禁止上传空文件；单文件大小默认限制为 50 MB。
- 删除脚本时同步删除 `scripts/<script_id>/` 目录。

## 3. 后端接口设计

新增蓝图文件：

- `routes/script_routes.py`
- `services/script_deploy.py`
- `database.models.ScriptModel`

注册到 `routes/__init__.py`，统一挂载 `/api`。

### 脚本 CRUD

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| `GET` | `/api/scripts` | 无 | 脚本列表 |
| `GET` | `/api/scripts/<id>` | 无 | 单个脚本详情 |
| `POST` | `/api/scripts` | `multipart/form-data` | 创建脚本 |
| `PUT` | `/api/scripts/<id>` | `multipart/form-data` | 更新脚本 |
| `DELETE` | `/api/scripts/<id>` | 无 | 删除脚本及本地文件 |

`POST/PUT` 表单字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | string | 脚本名称 |
| `script_type` | string | `php` 或 `shell` |
| `description` | string | 描述 |
| `remote_dir` | string | 远程脚本目录，默认 `/tmp` |
| `deploy_script` | string | Shell 部署脚本 |
| `files` | file[] | 新增上传文件，可多选 |
| `remove_files` | JSON string | 需要移除的已有文件名数组，仅 `PUT` 使用 |

列表返回字段：

```json
{
  "id": 1,
  "name": "部署 WAF",
  "script_type": "php",
  "description": "上传 PHP WAF 并写入入口",
  "remote_dir": "/tmp",
  "files": [
    {"filename": "waf.php", "size": 10240, "relative_path": "files/waf.php"}
  ],
  "file_count": 1,
  "created_at": "2026-06-23 16:00:00",
  "updated_at": "2026-06-23 16:00:00"
}
```

### 可写目录来源

复用现有接口：

```text
GET /api/servers/<server_id>/writable-dirs
```

前端新增/编辑脚本时，如果存在当前在线控制服务器，调用该接口加载可写目录选项；始终将 `/tmp` 放在第一项并作为默认值。若无在线控制服务器或接口失败，表单仍可使用，脚本目录默认 `/tmp`，并允许手动输入。

### 脚本部署

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| `POST` | `/api/servers/<server_id>/scripts/<script_id>/deploy` | 空 JSON | 部署结果 |

部署接口不再从请求体读取 `remote_dir`，统一使用脚本记录中的 `remote_dir` 字段。

部署流程：

1. 校验服务器存在。
2. 校验脚本存在。
3. 读取脚本 `remote_dir`，为空则使用 `/tmp`，并做远程目录安全校验。
4. 创建本地临时 tar：包含 `files/` 下所有包含文件和 `deploy.sh`。
5. 上传到远程：`<remote_dir>/awd_script_<script_id>_<timestamp>.tar`。
6. 解压到远程目录：`<remote_dir>/awd_script_<script_id>_<timestamp>/`。
7. 执行：

```bash
cd '<remote_extract_dir>' && chmod +x deploy.sh && bash deploy.sh '<server_web_root>' '<remote_extract_dir>'
```

8. 返回 stdout、stderr、exit_code、remote_extract_dir、remote_dir。
9. 清理远程 tar；保留解压目录，便于脚本部署后的文件引用。
10. 若上传、解压或执行前失败，清理远程 tar 和解压目录。

部署脚本约定：

- `$1`：目标服务器的 `web_root`。
- `$2`：远程解压目录，包含上传的所有文件。
- 部署脚本自身工作目录也是 `$2`。
- 包含文件在 `$2/files/` 下。

示例部署脚本：

```bash
set -e
WEB_ROOT="$1"
PACKAGE_DIR="$2"

mkdir -p "$WEB_ROOT"
cp "$PACKAGE_DIR/files/index.php" "$WEB_ROOT/index.php"
chmod 644 "$WEB_ROOT/index.php"
echo "deploy ok"
```

## 4. 前端交互设计

### 导航与页面

在 `templates/index.html` 主导航新增标签：

```text
脚本部署
```

新增面板：

```html
<section class="tab-panel" id="panel-scripts">
  <div class="script-content" id="scriptContent"></div>
</section>
```

新增静态文件：

```text
static/js/scripts.js
```

`app.js` 中新增：

- `switchTab('scripts')` 时调用 `initScriptsPage()`。
- 当前控制服务器切换后，如果当前页是 `scripts`，刷新脚本部署页。

### 脚本列表

列表列：

| 列 | 内容 |
| --- | --- |
| 脚本名称 | `name` |
| 脚本类型 | `php` / `shell` badge |
| 脚本描述 | `description` |
| 脚本目录 | `remote_dir` |
| 包含文件 | 文件名列表或 `N 个文件` |
| 操作 | 编辑、删除、部署 |

列表顶部：

- 「新增脚本」按钮。
- 无脚本时显示空状态：`暂无脚本，请点击新增脚本创建`。

### 新增/编辑模态框

字段：

- 脚本名称：文本输入。
- 脚本类型：下拉选择 `php`、`shell`。
- 脚本描述：textarea。
- 脚本目录：下拉选择当前控制服务器可写目录，默认 `/tmp`；提供「手动输入」选项。
- 包含文件：`input type="file" multiple`。
- 已有文件列表：展示文件名、大小、移除按钮。
- 部署脚本：大 textarea，使用 monospace 样式。
- 操作按钮：取消、保存。

编辑时：

- 默认填充已有字段，包括 `remote_dir`。
- 若已有 `remote_dir` 不在当前服务器可写目录列表中，仍保留为一个选项并标记为「当前值」。
- 已有文件点击「移除」后加入 `remove_files`，保存时提交。
- 新增上传文件和移除文件在一次 `PUT` 中完成。

### 部署交互

点击「部署」：

1. 若无当前在线控制服务器，提示：`暂无在线控制服务器，请先连接服务器`。
2. 弹出确认框，展示目标服务器名称、IP、脚本名称、脚本目录。
3. 点击确认后禁用按钮并显示 `部署中...`。
4. 部署完成后展示：
   - 成功/失败状态。
   - 脚本目录。
   - 远程解压目录。
   - 退出码。
   - stdout。
   - stderr。

## 5. 实现变更清单

后端：

- `config.py`：新增脚本存储和部署超时配置；不新增固定 `SCRIPT_REMOTE_BASE_DIR`。
- `database/db.py`：新增 `deployment_scripts` 建表逻辑，包含 `remote_dir` 字段。
- `database/models.py`：新增 `ScriptModel`，提供 list/get/create/update/delete。
- `services/script_deploy.py`：新增 `ScriptDeployManager`，负责本地文件管理、打包上传和远程执行。
- `routes/script_routes.py`：新增 CRUD 和 deploy API。
- `routes/__init__.py`：注册 `script_bp`。

前端：

- `templates/index.html`：新增「脚本部署」导航和面板，引入 `scripts.js`。
- `static/js/app.js`：接入新标签页、控制服务器切换刷新逻辑。
- `static/js/scripts.js`：实现列表、新增、编辑、删除、部署、脚本目录选择。
- `static/css/style.css`：补充脚本列表、文件列表、代码编辑 textarea、部署输出块样式。

文档：

- `README.md`：补充「脚本部署」功能、目录结构、API 概览和安全说明。

## 6. 安全与异常处理

- 所有接口必须使用 `login_required`。
- 文件名只允许保存 basename，不接受用户提交的路径。
- 删除脚本只允许删除 `SCRIPT_STORAGE_DIR/<id>` 下的文件，删除前校验绝对路径前缀。
- 部署脚本是高权限远程命令执行能力，README 和 UI 均提示仅在可信环境使用。
- `remote_dir` 必须是绝对路径，不允许为空、`/`、`/root`。
- 使用脚本记录的 `remote_dir` 作为远程上传和解压基准目录，所有远程路径使用单引号包裹。
- 上传和部署过程中出现异常时，返回明确错误信息。
- 部署脚本执行失败时不抛弃 stdout/stderr，前端展示完整诊断信息。
- 删除脚本失败时，如果数据库删除成功但文件残留，返回 warning 风格消息并记录残留路径。

## 7. 测试用例

### 数据库与模型

| 编号 | 场景 | 步骤 | 预期 |
| --- | --- | --- | --- |
| DB-01 | 初始化建表 | 启动 `init_db()` | 自动创建 `deployment_scripts` 表 |
| DB-02 | 创建脚本 | 调用模型创建合法 `php` 脚本 | 返回新 ID，数据库可查询 |
| DB-03 | 类型非法 | 创建 `python` 类型脚本 | 返回校验失败 |
| DB-04 | 名称重复 | 创建同名脚本 | 返回唯一约束或业务错误 |
| DB-05 | 默认脚本目录 | 创建脚本时不传 `remote_dir` | 保存为 `/tmp` |
| DB-06 | 修改脚本目录 | 编辑脚本 `remote_dir=/dev/shm` | 数据库更新为 `/dev/shm` |
| DB-07 | 删除脚本 | 删除存在脚本 | 数据库记录消失，本地目录被删除 |

### CRUD API

| 编号 | 场景 | 步骤 | 预期 |
| --- | --- | --- | --- |
| API-01 | 未登录访问列表 | 请求 `GET /api/scripts` | 返回 401 |
| API-02 | 获取空列表 | 登录后请求列表 | 返回 `success=true` 和空数组 |
| API-03 | 新增 shell 脚本 | multipart 提交名称、类型、描述、脚本目录、部署脚本 | 创建成功 |
| API-04 | 新增多文件 | 上传 2 个文件 | `files` 记录 2 个文件 |
| API-05 | 新增缺少名称 | 不传 `name` | 返回 400 |
| API-06 | 新增缺少部署脚本 | 不传 `deploy_script` | 返回 400 |
| API-07 | 新增非法脚本目录 | `remote_dir="/"` | 返回 400 |
| API-08 | 获取详情 | 请求 `/api/scripts/<id>` | 返回完整字段、脚本目录和文件列表 |
| API-09 | 编辑基础字段 | 修改名称、类型、描述、脚本目录、部署脚本 | 返回成功，详情更新 |
| API-10 | 编辑移除文件 | `remove_files=["a.php"]` | 文件元数据和本地文件均移除 |
| API-11 | 编辑新增文件 | 上传新文件 `b.sh` | 文件列表新增 |
| API-12 | 删除脚本 | 请求 `DELETE /api/scripts/<id>` | 数据库和本地文件删除 |
| API-13 | 删除不存在脚本 | 删除不存在 ID | 返回 404 |

### 部署服务

| 编号 | 场景 | 步骤 | 预期 |
| --- | --- | --- | --- |
| DEP-01 | 部署成功 | 脚本目录 `/tmp`，deploy.sh 输出 `ok` 并 exit 0 | 返回 success、exit_code=0、stdout 包含 `ok` |
| DEP-02 | 使用脚本目录 | 脚本目录 `/dev/shm`，执行部署 | tar 和解压目录都位于 `/dev/shm` |
| DEP-03 | 无当前服务器 | 使用不存在 server_id | 返回服务器不存在 |
| DEP-04 | 脚本不存在 | 使用不存在 script_id | 返回脚本不存在 |
| DEP-05 | 脚本目录非法 | 数据中 `remote_dir="/"` | 返回 400，不执行 SSH |
| DEP-06 | 上传失败 | mock `upload_file` 抛异常 | 返回部署失败，并清理本地临时 tar |
| DEP-07 | 解压失败 | mock `tar xf` 非 0 | 返回失败，清理远程临时文件 |
| DEP-08 | 脚本执行失败 | deploy.sh `exit 2` | 返回 deploy_failed，包含 stdout/stderr/exit_code |
| DEP-09 | 多文件部署 | 上传多个文件后执行 `ls files` | stdout 中包含所有文件名 |
| DEP-10 | 参数约定 | deploy.sh 输出 `$1` `$2` | stdout 中分别为 web_root 和远程解压目录 |
| DEP-11 | 清理策略 | 部署完成 | 远程 tar 被删除，远程解压目录保留 |

### 前端交互

| 编号 | 场景 | 步骤 | 预期 |
| --- | --- | --- | --- |
| UI-01 | 标签页展示 | 打开首页 | 导航出现「脚本部署」 |
| UI-02 | 空状态 | 无脚本进入页面 | 展示空状态和新增按钮 |
| UI-03 | 新增脚本 | 点击新增，填写字段，选择脚本目录，上传文件，保存 | 模态框关闭，列表新增记录 |
| UI-04 | 脚本目录默认值 | 当前无可写目录数据时打开新增 | 脚本目录默认 `/tmp` |
| UI-05 | 加载可写目录 | 当前有在线控制服务器时打开新增 | 下拉展示 `/tmp` 和接口返回的可写目录 |
| UI-06 | 表单校验 | 新增时缺少名称或部署脚本 | 前端提示错误，不提交 |
| UI-07 | 编辑脚本 | 点击编辑，修改描述和脚本目录，保存 | 列表描述和脚本目录更新 |
| UI-08 | 移除文件 | 编辑时移除已有文件 | 保存后文件列表减少 |
| UI-09 | 删除确认 | 点击删除并取消 | 脚本仍在列表 |
| UI-10 | 删除确认成功 | 点击删除并确认 | 列表移除脚本 |
| UI-11 | 无在线服务器部署 | 当前无控制服务器点击部署 | 提示先连接服务器 |
| UI-12 | 部署确认展示目录 | 点击部署 | 确认框展示脚本目录 |
| UI-13 | 部署成功展示 | 部署返回 stdout/stderr | 页面展示脚本目录、远程解压目录和部署结果 |
| UI-14 | 部署失败展示 | 后端返回 exit_code 非 0 | 页面展示错误、stdout/stderr 和退出码 |

### 回归测试

| 编号 | 场景 | 步骤 | 预期 |
| --- | --- | --- | --- |
| REG-01 | 原服务器管理 | 新增并连接服务器 | 原流程不受影响 |
| REG-02 | 原可写目录接口 | 请求 `/api/servers/<id>/writable-dirs` | 仍返回可写目录数组 |
| REG-03 | 原 WAF 部署 | 进入 WAF 标签页加载列表 | 原 WAF 列表正常 |
| REG-04 | 原备份恢复 | 进入备份页面加载当前控制服务器 | 页面正常 |
| REG-05 | 原监控告警 | 进入监控页面加载状态 | 页面正常 |
| REG-06 | 认证拦截 | 退出登录后请求脚本接口 | 正常返回 401 或跳转登录 |

## 8. 验收标准

- 可在页面完成脚本新增、查看、编辑、删除。
- 列表展示脚本名称、类型、描述、脚本目录、包含文件和操作。
- 新增和编辑时可选择当前控制服务器可写目录，默认 `/tmp`，也可手动输入目录。
- 支持上传多个包含文件，并能在编辑时追加或移除。
- 删除脚本会删除数据库记录、本地包含文件和部署脚本。
- 可选择当前在线控制服务器执行脚本部署。
- 部署接口会使用脚本目录字段作为远程上传和解压基准目录。
- 部署接口会上传包含文件和部署脚本，在远程服务器执行 Shell，并展示执行输出。
- 所有新增接口受登录保护。
- 新增模块不影响现有服务器管理、备份恢复、WAF 部署、监控告警功能。
