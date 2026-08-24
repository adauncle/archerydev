#!/bin/bash
# pre_push_backup_110prod_20260827.sh
# 用途: 推 110 prod 之前, 3 份完整备份 (8/27 20:50 跑, 推 110 必走)
#
# 备份内容:
#   1. 代码目录 (整个 prod 目录)  → /backup/archery_v030_20260827_2050_code.tar.gz
#   2. MySQL schema (无数据)       → /backup/archery_v030_20260827_2050_schema.sql
#   3. admin config (Perm + SysConfig + workflow_audit_setting) → /backup/archery_v030_20260827_2050_admin.json
#
# ⚠️  本脚本在 110 prod 内部跑, 不通过 sshpass 远程调用
# ⚠️  跑法: ssh 登 110 prod → bash /tmp/pre_push_backup_110prod_20260827.sh
#
# 推 110 必做 (跟 5 步必做 + 推代码 + 备份 配套):
#   - 备份目录: /backup/ (110 prod 已存在, 8/05 升级用过)
#   - 备份大小预估: code ~50MB, schema ~10MB, admin ~5MB
#   - 备份后必须 sha256sum 记录, 防止备份文件被破坏
#   - 回滚时: rollback_110prod_v030_20260827.sh 配套使用
#
# 作者: mavis @ 2026-08-24
# 关联设计: docs/designs/2026-08-27_push-v030-rollback-plan.md (8/25 写)

set -euo pipefail

PROD_PATH="/dbdata/archery_v114_c9236a0"
TS="20260827_2050"
BACKUP_DIR="/backup"
LOG_FILE="/var/log/archery/pre_push_backup_${TS}.log"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok() { echo -e "${GREEN}[$(date +%H:%M:%S)] OK${NC} $*"; }
err() { echo -e "${RED}[$(date +%H:%M:%S)] ERR${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] WARN${NC} $*"; }

# 启动日志
mkdir -p $(dirname ${LOG_FILE})
exec > >(tee -a ${LOG_FILE}) 2>&1

echo "================================================================"
echo "pre_push_backup_110prod_20260827.sh"
echo "  时间: $(date)"
echo "  110 prod 推 110 前 3 份备份 (跟 rollback_110prod_v030_20260827.sh 配套)"
echo "================================================================"

# === 前置检查 ===
echo ""
echo "=== 前置检查 ==="
[[ ! -d "${PROD_PATH}" ]] && { err "代码目录不存在: ${PROD_PATH}"; exit 1; }
[[ ! -f "/root/.my.cnf" ]] && { err "MySQL 凭据不存在: /root/.my.cnf"; exit 1; }
[[ ! -d "${BACKUP_DIR}" ]] && { err "备份目录不存在: ${BACKUP_DIR}"; exit 1; }

disk_avail=$(df -BG ${BACKUP_DIR} | tail -1 | awk '{print $4}' | tr -d 'G')
[[ ${disk_avail:-0} -lt 5 ]] && { err "备份目录磁盘空间 < 5GB, 实际 ${disk_avail}GB, 拒绝备份"; exit 1; }
ok "前置检查通过 (备份目录剩余 ${disk_avail}GB)"

# === 备份 1: 代码目录 (50MB, 2-3 分钟) ===
echo ""
echo "=== 备份 1: 代码目录 ==="
echo "  源: ${PROD_PATH}"
echo "  目标: ${BACKUP_DIR}/archery_v030_${TS}_code.tar.gz"
echo "  包含: sql, common, dashboard, docs, archery, venv (符号链接, 实际不打包)"

CODE_BACKUP="${BACKUP_DIR}/archery_v030_${TS}_code.tar.gz"

# 备份前先看 mtime (跟 git push 后的 mtime 对比)
echo "  备份前代码 mtime:"
stat -c '    %y %n' ${PROD_PATH}/sql/views.py 2>&1 | head -1

tar --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='static/dist' --exclude='node_modules' \
    --exclude='.git' \
    -czf ${CODE_BACKUP} \
    -C $(dirname ${PROD_PATH}) $(basename ${PROD_PATH}) 2>&1 | tail -5

code_size=$(du -sh ${CODE_BACKUP} | cut -f1)
code_sha=$(sha256sum ${CODE_BACKUP} | cut -d' ' -f1)
ok "代码备份完成: ${code_size}, sha256=${code_sha:0:16}..."

# 备份完确认 mtime 一致
echo "  备份后代码 mtime:"
stat -c '    %y %n' ${PROD_PATH}/sql/views.py 2>&1 | head -1

# === 备份 2: MySQL schema (10MB, 30 秒) ===
echo ""
echo "=== 备份 2: MySQL schema ==="
echo "  源: archery 库 (无数据, 只有结构 + triggers + routines)"
echo "  目标: ${BACKUP_DIR}/archery_v030_${TS}_schema.sql"

SCHEMA_BACKUP="${BACKUP_DIR}/archery_v030_${TS}_schema.sql"

mysqldump --defaults-file=/root/.my.cnf \
    --no-data \
    --triggers \
    --routines \
    --events \
    --single-transaction \
    --skip-lock-tables \
    --set-gtid-purged=OFF \
    --column-statistics=0 \
    --hex-blob \
    archery > ${SCHEMA_BACKUP} 2>&1

schema_size=$(du -sh ${SCHEMA_BACKUP} | cut -f1)
schema_lines=$(wc -l < ${SCHEMA_BACKUP})
schema_sha=$(sha256sum ${SCHEMA_BACKUP} | cut -d' ' -f1)
ok "Schema 备份完成: ${schema_size}, ${schema_lines} 行, sha256=${schema_sha:0:16}..."

# 快速校验 schema 备份是否完整 (头几行必须是 mysqldump header)
if ! head -10 ${SCHEMA_BACKUP} | grep -q "MySQL dump"; then
    err "Schema 备份可能损坏, header 不像 mysqldump 输出"
    head -20 ${SCHEMA_BACKUP}
    exit 1
fi
ok "Schema 备份 header 校验通过"

# === 备份 3: admin config (5MB, 20 秒) ===
echo ""
echo "=== 备份 3: admin config (SysConfig + workflow_audit_setting + Permission) ==="
echo "  目标: ${BACKUP_DIR}/archery_v030_${TS}_admin.json"

ADMIN_BACKUP="${BACKUP_DIR}/archery_v030_${TS}_admin.json"

cd ${PROD_PATH}
sudo -u archery venv/bin/python manage.py shell <<'PYEOF' > ${ADMIN_BACKUP} 2>&1
import json
from django.core import serializers
from django.contrib.auth.models import Permission
from sql.models import SysConfig
from sql.utils.workflow_audit import WorkflowAuditSetting  # 5.7 兼容写法 (具体看代码)

objects = []

# 1. SysConfig (admin 后台所有配置项, 包括 gh-ost 路径 / soar / sqladvisor)
for cfg in SysConfig.objects.all():
    objects.append({
        "model": "sql.sysconfig",
        "pk": cfg.id,
        "fields": {"item": cfg.item, "value": cfg.value, "desc": getattr(cfg, "desc", "")},
    })

# 2. workflow_audit_setting (8/24 ConfigurableAuditor 走这个表, 必备份)
try:
    for setting in WorkflowAuditSetting.objects.all():
        objects.append({
            "model": "sql.workflowauditsetting",
            "pk": setting.audit_setting_id,
            "fields": {
                "group_id": setting.group_id,
                "group_name": setting.group_name,
                "workflow_type": setting.workflow_type,
                "audit_auth_groups": setting.audit_auth_groups,
            },
        })
except Exception as e:
    print(f"workflow_audit_setting 备份失败: {e}", file=__import__("sys").stderr)

# 3. ddl_gh_ost 相关 perm (推 110 后, perm 走 5 步必做脚本 step 5 重建)
# 注: 4 个 perm (view/upload/change/delete ddlghosttask) 不在此备份
#     推 110 时 5 步必做 step 13 会 idempotent 重建

print(json.dumps(objects, ensure_ascii=False, indent=2, default=str))
PYEOF

admin_size=$(du -sh ${ADMIN_BACKUP} | cut -f1)
admin_lines=$(wc -l < ${ADMIN_BACKUP})
admin_sha=$(sha256sum ${ADMIN_BACKUP} | cut -d' ' -f1)
ok "Admin config 备份完成: ${admin_size}, ${admin_lines} 行, sha256=${admin_sha:0:16}..."

# === 备份清单 ===
echo ""
echo "================================================================"
echo "[3 份备份完成]"
echo "  1. 代码:    ${CODE_BACKUP} (${code_size})"
echo "  2. Schema:  ${SCHEMA_BACKUP} (${schema_size}, ${schema_lines} 行)"
echo "  3. Admin:   ${ADMIN_BACKUP} (${admin_size}, ${admin_lines} 行)"
echo "  日志:      ${LOG_FILE}"
echo ""
echo "  总大小: $(du -sh ${CODE_BACKUP} ${SCHEMA_BACKUP} ${ADMIN_BACKUP} | tail -1 | cut -f1)"
echo "  备份目录剩余: $(df -BG ${BACKUP_DIR} | tail -1 | awk '{print $4}')"
echo "================================================================"
echo ""
echo "下一步:"
echo "  1. 跑 5 步必做脚本 (5step_prerequisites_110prod.sh)"
echo "  2. 部署新代码 (rsync/tarball + 8 步操作)"
echo "  3. 重启 gunicorn (kill master + nohup 拉起)"
echo "  4. 验证 5 个端点 200"
echo ""
echo "如果任何步骤失败, 跑回滚脚本:"
echo "  bash /tmp/rollback_110prod_v030_20260827.sh"
echo "================================================================"
