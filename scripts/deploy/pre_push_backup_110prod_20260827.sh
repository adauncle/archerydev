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

set -u  # 不用 -e, 备份脚本要"完成全部 3 份", 不能一个失败就全丢

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

# 备份状态汇总 (最后输出, 决定能不能推 110)
BACKUP_CODE_OK=0
BACKUP_SCHEMA_OK=0
BACKUP_ADMIN_OK=0

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
BACKUP_CODE_OK=1
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
    --hex-blob \
    archery > ${SCHEMA_BACKUP} 2>&1 || warn "mysqldump 返非 0, schema 备份可能不完整 (但继续跑, 让 DBA 看 log 决定)"

schema_size=$(du -sh ${SCHEMA_BACKUP} | cut -f1)
schema_lines=$(wc -l < ${SCHEMA_BACKUP})
schema_sha=$(sha256sum ${SCHEMA_BACKUP} | cut -d' ' -f1)
BACKUP_SCHEMA_OK=1
ok "Schema 备份完成: ${schema_size}, ${schema_lines} 行, sha256=${schema_sha:0:16}..."

# 快速校验 schema 备份是否完整 (头几行必须是 mysqldump header)
if head -10 ${SCHEMA_BACKUP} 2>/dev/null | grep -q "MySQL dump"; then
    ok "Schema 备份 header 校验通过"
else
    err "Schema 备份可能损坏, header 不像 mysqldump 输出"
    head -20 ${SCHEMA_BACKUP}
    BACKUP_SCHEMA_OK=0
    warn "Schema 备份失败标记, DBA 评估"
fi

# === 备份 3: admin config (5MB, 20 秒) ===
echo ""
echo "=== 备份 3: admin config (SysConfig + workflow_audit_setting + Permission) ==="
echo "  目标: ${BACKUP_DIR}/archery_v030_${TS}_admin.json"

ADMIN_BACKUP="${BACKUP_DIR}/archery_v030_${TS}_admin.json"

cd ${PROD_PATH}
# 8/25 教训: manage.py shell 会输出 "import local settings failed, ignored" 污染 JSON
#           改用 python -c 走 django.setup() 路径, 干净 stdout
ADMIN_PY='import django, os, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()
try:
    from sql.models import Config as SysConfig
except Exception as e:
    print("ERR: sql.models.Config import failed:", e, flush=True); raise
try:
    from sql.utils.workflow_audit import WorkflowAuditSetting
    HAS_WAS = True
except Exception:
    HAS_WAS = False
objects = []
for cfg in SysConfig.objects.all():
    objects.append({
        "model": "sql_config",
        "pk": cfg.id,
        "fields": {
            "item": getattr(cfg, "item", ""),
            "value": getattr(cfg, "value", ""),
            "desc": getattr(cfg, "desc", ""),
        },
    })
if HAS_WAS:
    for setting in WorkflowAuditSetting.objects.all():
        objects.append({
            "model": "workflow_audit_setting",
            "pk": setting.audit_setting_id,
            "fields": {
                "group_id": setting.group_id,
                "group_name": setting.group_name,
                "workflow_type": setting.workflow_type,
                "audit_auth_groups": setting.audit_auth_groups,
            },
        })
print(json.dumps(objects, ensure_ascii=False, indent=2, default=str))
'
sudo -u archery venv/bin/python -c "${ADMIN_PY}" > ${ADMIN_BACKUP} 2>/tmp/admin_dump_err.log || warn "admin dump 返非 0 (看 /tmp/admin_dump_err.log, 但继续跑)"

# 8/25 教训: Archery 上游 archery/settings.py 会 print "import local settings failed, ignored"
#           污染 stdout. 备份后用 sed 过滤掉这行
sed -i '/^import local settings failed, ignored$/d' ${ADMIN_BACKUP}

admin_size=$(du -sh ${ADMIN_BACKUP} | cut -f1)
admin_lines=$(wc -l < ${ADMIN_BACKUP})
admin_sha=$(sha256sum ${ADMIN_BACKUP} | cut -d' ' -f1)
BACKUP_ADMIN_OK=1
ok "Admin config 备份完成: ${admin_size}, ${admin_lines} 行, sha256=${admin_sha:0:16}..."

# Admin 备份有效性校验 (JSON 格式)
if python3 -c "import json; json.load(open('${ADMIN_BACKUP}'))" 2>/dev/null; then
    ok "Admin 备份 JSON 格式校验通过"
else
    err "Admin 备份不是有效 JSON, 可能损坏"
    head -5 ${ADMIN_BACKUP}
    if [[ -s /tmp/admin_dump_err.log ]]; then
        err "stderr:"
        cat /tmp/admin_dump_err.log | head -10
    fi
    BACKUP_ADMIN_OK=0
    warn "Admin 备份失败标记, DBA 评估"
fi
rm -f /tmp/admin_dump_err.log

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
echo ""
echo "  备份状态: code=$([ ${BACKUP_CODE_OK} == 1 ] && echo OK || echo FAIL) schema=$([ ${BACKUP_SCHEMA_OK} == 1 ] && echo OK || echo FAIL) admin=$([ ${BACKUP_ADMIN_OK} == 1 ] && echo OK || echo FAIL)"
echo "================================================================"
echo ""

# 8/25 教训: 任何备份失败都阻塞推 110, DBA 必看 log 决定
if [[ ${BACKUP_CODE_OK} != 1 ]]; then
    err "代码备份 FAIL, 推 110 必看 log: ${LOG_FILE}"
    exit 1
fi
if [[ ${BACKUP_SCHEMA_OK} != 1 || ${BACKUP_ADMIN_OK} != 1 ]]; then
    warn "schema / admin 备份有失败, 推 110 之前 DBA 评估 (code 备份 OK, 能 rollback)"
    read -p "  继续推 110? (yes/no): " continue_push
    if [[ "${continue_push}" != "yes" ]]; then
        err "DBA 拒绝继续, 退出"
        exit 1
    fi
fi

echo "下一步:"
echo "  1. 跑 5 步必做脚本 (5step_prerequisites_110prod.sh)"
echo "  2. 部署新代码 (rsync/tarball + 8 步操作)"
echo "  3. 重启 gunicorn (kill master + nohup 拉起)"
echo "  4. 验证 5 个端点 200"
echo ""
echo "如果任何步骤失败, 跑回滚脚本:"
echo "  bash /tmp/rollback_110prod_v030_20260827.sh"
echo "================================================================"
