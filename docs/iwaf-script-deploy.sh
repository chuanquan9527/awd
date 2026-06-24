#!/usr/bin/env bash
# iWAF 部署脚本，适用于 AWD 工作台的「脚本部署」模块。
#
# 使用前需要在「包含文件」中上传：
#   - waf.php
#   - waf_x86_64.so（可选，用于 x86_64 Linux 上的 LD_PRELOAD 防护）
#
# 工作台执行部署脚本时会自动传入：
#   $1 = 目标服务器 Web 根目录，即服务器配置里的 web_root
#   $2 = 远程解压目录，即工作台上传并解压脚本包后的目录
#
# 面板密码和入口 key 的配置方式：
#   1. 推荐在下方 DEFAULT_* 两行中填写固定值，便于通过 UI 直接部署。
#   2. 也可在远程环境中预先设置 IWAF_ADMIN_PASSWORD / IWAF_PANEL_KEY。
#   3. 如果都为空，iWAF 会自动生成密码和 key，并在安装输出中打印。
#
# 注意：
#   - 脚本会临时复制 waf.php 到 /tmp/waf_install.php 执行安装。
#   - 安装结束后会清理 /tmp/waf_install.php 和 /tmp/waf_x86_64.so。
#   - 脚本会尽量从 .user.ini 中识别 iWAF 隐藏目录并设置 777 权限。
#   - 重复部署可能会再次注入或生成新的隐藏目录，建议部署前先备份 Web 目录。

set -Eeuo pipefail

WEB_ROOT="${1:-/var/www/html}"
PACKAGE_DIR="${2:-$(cd "$(dirname "$0")" && pwd)}"
FILES_DIR="${PACKAGE_DIR}/files"

# 如果希望通过「脚本部署」UI 一键固定密码和 key，直接修改这两个值。
# 示例：
#   DEFAULT_IWAF_ADMIN_PASSWORD="Admin@12345678!"
#   DEFAULT_IWAF_PANEL_KEY="my_waf_key"
DEFAULT_IWAF_ADMIN_PASSWORD=""
DEFAULT_IWAF_PANEL_KEY=""

IWAF_ADMIN_PASSWORD="${IWAF_ADMIN_PASSWORD:-$DEFAULT_IWAF_ADMIN_PASSWORD}"
IWAF_PANEL_KEY="${IWAF_PANEL_KEY:-$DEFAULT_IWAF_PANEL_KEY}"

INSTALL_PHP="/tmp/waf_install.php"
INSTALL_SO="/tmp/waf_x86_64.so"

cleanup() {
  # 无论部署成功或失败，都清理临时安装文件，避免在 /tmp 泄露 WAF 安装入口。
  rm -f "$INSTALL_PHP" "$INSTALL_SO" 2>/dev/null || true
}
trap cleanup EXIT

fail() {
  echo "[ERROR] $*" >&2
  exit 1
}

info() {
  echo "[iWAF] $*"
}

# iWAF 安装器依赖目标服务器上的 PHP CLI。
if ! command -v php >/dev/null 2>&1; then
  fail "php command not found on target server"
fi

# web_root 必须存在，否则 iWAF 无法写入 .user.ini / .htaccess / 隐藏目录。
if [ ! -d "$WEB_ROOT" ]; then
  fail "web_root is not a directory: $WEB_ROOT"
fi

# waf.php 是必需文件；它应通过「包含文件」上传到 $PACKAGE_DIR/files/。
if [ ! -f "$FILES_DIR/waf.php" ]; then
  fail "missing required file: $FILES_DIR/waf.php"
fi

info "web_root: $WEB_ROOT"
info "package_dir: $PACKAGE_DIR"

# 按 iWAF 原始部署流程，将核心安装器复制到 /tmp 后执行。
cp "$FILES_DIR/waf.php" "$INSTALL_PHP"

if [ -f "$FILES_DIR/waf_x86_64.so" ]; then
  # waf.php 会在安装 LD_PRELOAD 防护时从自身目录查找 waf_x86_64.so。
  cp "$FILES_DIR/waf_x86_64.so" "$INSTALL_SO"
  info "loaded optional LD_PRELOAD library: waf_x86_64.so"
else
  info "optional waf_x86_64.so not found, iWAF will skip precompiled LD_PRELOAD copy"
fi

# 使用 Bash 数组拼装命令，避免密码或 key 中的特殊字符破坏命令行。
INSTALL_CMD=(php "$INSTALL_PHP" --install "$WEB_ROOT")
if [ -n "$IWAF_ADMIN_PASSWORD" ]; then
  INSTALL_CMD+=(--password "$IWAF_ADMIN_PASSWORD")
fi
if [ -n "$IWAF_PANEL_KEY" ]; then
  INSTALL_CMD+=(--key "$IWAF_PANEL_KEY")
fi

info "starting iWAF installer"
"${INSTALL_CMD[@]}"

HIDDEN_DIR=""
USER_INI="$WEB_ROOT/.user.ini"

# 优先从 .user.ini 中读取 auto_prepend_file 指向的真实隐藏目录。
# 某些容器环境里 iWAF 实际路径可能不是传入的 WEB_ROOT，因此不要只依赖 find。
if [ -f "$USER_INI" ]; then
  HIDDEN_DIR="$(
    sed -n 's/.*auto_prepend_file[[:space:]]*=[[:space:]]*\(.*\)\/common\.inc\.php.*/\1/p' "$USER_INI" 2>/dev/null | head -n 1
  )"
fi

# 如果 .user.ini 解析失败，再回退到 web_root 下查找 .xxxxxxxx 隐藏目录。
if [ -z "$HIDDEN_DIR" ]; then
  HIDDEN_DIR="$(
    find "$WEB_ROOT" -maxdepth 1 -type d -name '.[a-z0-9]*' 2>/dev/null \
      | while read -r d; do
          base="$(basename "$d")"
          if echo "$base" | grep -Eq '^\.[a-z0-9]{8}$' && [ -f "$d/common.inc.php" ]; then
            echo "$d"
            break
          fi
        done
  )"
fi

if [ -n "$HIDDEN_DIR" ] && [ -d "$HIDDEN_DIR" ]; then
  # iWAF 部署后会生成配置、日志、基线等运行文件，比赛环境中宽权限更少踩坑。
  # 如需更严格权限，可按 Web 服务用户调整为 chown + 750/640。
  if chmod -R 777 "$HIDDEN_DIR" 2>/dev/null; then
    info "set hidden iWAF directory permissions to 777: $HIDDEN_DIR"
  else
    info "warning: hidden iWAF directory found but chmod failed: $HIDDEN_DIR"
  fi
else
  info "warning: iWAF hidden directory not found"
fi

# 最后做一个轻量状态检查，方便在工作台部署结果中直接判断是否挂载成功。
if [ -f "$USER_INI" ] && grep -q 'auto_prepend_file' "$USER_INI"; then
  info ".user.ini auto_prepend_file is configured"
else
  info "warning: .user.ini auto_prepend_file not detected"
fi

info "iWAF deployment completed"
info "panel entry: http://<host>/<any_php_file>?waf_key=<panel_key>"
