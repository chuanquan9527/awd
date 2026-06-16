#!/bin/bash
# iWAF 部署脚本
# 参数: $1=web根目录 $2=管理密码(可选) $3=面板key(可选)
# 工作目录为tar解压后的目录（固定在 /tmp 下）

WEB_ROOT="${1:-/var/www/html}"
PASSWORD="${2:-}"
KEY="${3:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 将 waf.php 复制到 /tmp 下执行安装（固定使用 /tmp）
cp "${SCRIPT_DIR}/waf.php" /tmp/waf_install.php

# 如果存在 so 文件也复制到 /tmp
if [ -f "${SCRIPT_DIR}/waf_x86_64.so" ]; then
    cp "${SCRIPT_DIR}/waf_x86_64.so" /tmp/waf_x86_64.so
fi

# 执行安装
INSTALL_CMD="php /tmp/waf_install.php --install ${WEB_ROOT}"
if [ -n "$PASSWORD" ]; then
    INSTALL_CMD="${INSTALL_CMD} --password ${PASSWORD}"
fi
if [ -n "$KEY" ]; then
    INSTALL_CMD="${INSTALL_CMD} --key ${KEY}"
fi

eval "$INSTALL_CMD"

# 安装完成后立即删除安装文件
rm -f /tmp/waf_install.php /tmp/waf_x86_64.so

# 授予 WAF 自动生成的隐藏目录权限 777
# iWAF 可能使用容器内路径（如 /app）而非传入的 WEB_ROOT
# 策略: 从 .user.ini 中提取隐藏目录的实际路径

HIDDEN_DIR=""

# 从 .user.ini 中提取隐藏目录路径
# 格式: auto_prepend_file = /app/.5732a981/common.inc.php
if [ -f "${WEB_ROOT}/.user.ini" ]; then
    HIDDEN_DIR=$(grep -oP 'auto_prepend_file\s*=\s*\K\S+(?=/common\.inc\.php)' "${WEB_ROOT}/.user.ini" 2>/dev/null)
fi

# 如果提取失败，尝试在传入的 WEB_ROOT 下正则匹配
if [ -z "$HIDDEN_DIR" ]; then
    HIDDEN_DIR=$(find "${WEB_ROOT}" -maxdepth 1 -type d -regextype posix-extended -regex "^${WEB_ROOT}/\.[a-z0-9]{8}$" 2>/dev/null | head -1)
fi

if [ -n "$HIDDEN_DIR" ]; then
    chmod -R 777 "$HIDDEN_DIR"
    echo "已设置权限 777: $HIDDEN_DIR"
else
    echo "警告: 未找到 iWAF 隐藏目录"
fi

echo "iWAF部署完成，安装文件已清理"
