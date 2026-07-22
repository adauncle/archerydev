#!/usr/bin/env bash
# install_goinception.sh
# 在 172.20.2.134 上装 goInception v1.3.0 (Go 单体二进制)
# 走本地下载 + scp 上传 + 解压 + systemd 部署
#
# 用法（在 Windows 本地执行）:
#   1) 先把 goInception 包下到本地:
#      Invoke-WebRequest ... -OutFile goInception.tar.gz
#   2) 然后 scp 上去 + 跑本脚本
#
# 本脚本需要在 172.20.2.134 上以 root 跑（systemd 需要 root）
# 或: ssh root@172.20.2.134 'bash -s' < install_goinception.sh

set -euo pipefail

GOINCEPTION_VERSION="${GOINCEPTION_VERSION:-v1.3.0}"
GOINCEPTION_ASSET="goInception-linux-v1.3.0-94-g2f06c61b95.tar.gz"
GOINCEPTION_TARBALL="/tmp/${GOINCEPTION_ASSET}"
GOINCEPTION_INSTALL_DIR="/opt/goinception"
GOINCEPTION_CONFIG="${GOINCEPTION_INSTALL_DIR}/config/config.toml"
GOINCEPTION_BIN="${GOINCEPTION_INSTALL_DIR}/goInception"
SERVICE_FILE="/etc/systemd/system/goinception.service"
PORT=4000

echo "=========================================="
echo "1) 准备目录"
echo "=========================================="
mkdir -p "${GOINCEPTION_INSTALL_DIR}/config"

echo "=========================================="
echo "2) 复制二进制"
echo "=========================================="
if [[ ! -f "${GOINCEPTION_BIN}" ]]; then
  echo "  ERROR: ${GOINCEPTION_BIN} 不存在，先 scp goInception.tar.gz 上去并解压"
  exit 1
fi
chmod 755 "${GOINCEPTION_BIN}"

echo "=========================================="
echo "3) 写默认 config.toml"
echo "=========================================="
if [[ ! -f "${GOINCEPTION_CONFIG}" ]]; then
  cat > "${GOINCEPTION_CONFIG}" <<'EOF'
# GoInception Configuration.
host = "0.0.0.0"
port = 4000
path = "/tmp/tidb"
ignore_sighup = true

[log]
level = "info"
format = "text"
disable-timestamp = false

[log.file]
filename = ""
max-size = 300
max-days = 0
max-backups = 0
log-rotate = true

[inc]
backup_host = ""
backup_port = 0
backup_user = ""
backup_password = ""
enable_alter_database = false
enable_zero_date = true
enable_nullable = true
enable_drop_table = false
enable_set_engine = true
enable_timestamp_type = true
enable_change_column = true
check_timestamp_count = true
check_table_comment = false
check_column_comment = false
check_float_double = false
EOF
fi

echo "=========================================="
echo "4) 写 systemd service"
echo "=========================================="
cat > "${SERVICE_FILE}" <<'EOF'
[Unit]
Description=GoInception SQL Audit Engine
Documentation=https://github.com/hanchuanchuan/goInception
After=network.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/goinception
ExecStart=/opt/goinception/goInception -config=/opt/goinception/config/config.toml
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# CentOS 7 SELinux: 必须 chcon 才能被 systemd 加载
chcon -v -t systemd_unit_file_t "${SERVICE_FILE}" 2>/dev/null || true

echo "=========================================="
echo "5) 启用 + 启动 goinception"
echo "=========================================="
systemctl daemon-reload
systemctl enable goinception
systemctl restart goinception
sleep 2

echo "=========================================="
echo "6) 验证"
echo "=========================================="
systemctl status goinception --no-pager | head -10 || true
echo "---"
ss -tlnp 2>/dev/null | grep ":${PORT} " || echo "  WARN: port ${PORT} not listening"
echo "---"
curl -s -m 3 "http://127.0.0.1:${PORT}/" 2>&1 | head -c 200 || true
echo

echo "=========================================="
echo "DONE"
echo "=========================================="
echo "goInception 安装路径: ${GOINCEPTION_INSTALL_DIR}"
echo "监听端口: ${PORT}"
echo "service: systemctl {start|stop|status|restart} goinception"
echo "日志: journalctl -u goinception -f"
echo ""
echo "下一步: 在 Archery 端配 SysConfig (sql/engines/goinception.py 读取):"
echo "  - go_inception_host = 127.0.0.1"
echo "  - go_inception_port = 4000"
echo "  - go_inception_user = 'root' (任意非空字符串，goInception 不真鉴权)"
echo "  - go_inception_password = ''"
echo "  - inception_remote_backup_* (执行时回滚备份用，先留空)"
echo ""
echo "配置示例见: scripts/deploy/configure_goinception.py"
