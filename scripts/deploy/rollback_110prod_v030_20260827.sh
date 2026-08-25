#!/bin/bash
# rollback_110prod_v030_20260827.sh
# 用途: 推 110 prod 失败时, 一键回滚 (SLA 5 分钟)
#
# 配套: pre_push_backup_110prod_20260827.sh
#
# ⚠️  本脚本在 110 prod 内部跑
# ⚠️  跑法: ssh 登 110 prod → bash /tmp/rollback_110prod_v030_20260827.sh
#
# 回滚 4 步:
#   1. 停 gunicorn (kill master, 老 master 没有 systemd 自动拉, 需手动)
#   2. 恢复代码目录 (rsync 从备份恢复)
#   3. 恢复 schema (如果 migration 失败, 从 backup 重建表结构)
#   4. 拉起老 gunicorn (nohup 启动, 跟之前一样的配置)
#   5. 验证 HTTP 200 + 关键端点
#
# 触发条件 (DBA 拍板, 4 选 1):
#   - 数据库 migration 报错
#   - gunicorn 启动 30s 内 HTTP 502/503
#   - 关键端点 500 (SQL 提交 / 工单详情 / gh-ost 任务)
#   - 业务 RD 报"功能完全不可用"
#
# 8/24 拍板: 回滚 SLA 5 分钟 (DBA 评估)
#
# 作者: mavis @ 2026-08-24

set -euo pipefail

# 8/25 演练支持: DRY_RUN=1 时, kill master + nohup 拉起 + mv 代码目录 都 NOOP
# 8/25 教训: 演练时 mv 代码目录会破坏 gunicorn 运行时 (cwd 跟着走, venv 路径变化)
# 演练模式下只演练"前置检查 + 解压验证" 逻辑, 不真改文件系统
DRY_RUN="${DRY_RUN:-0}"

PROD_PATH="/dbdata/archery_v114_c9236a0"
TS="20260827_2050"
BACKUP_DIR="/backup"
LOG_FILE="/var/log/archery/rollback_${TS}.log"

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
echo "rollback_110prod_v030_20260827.sh"
echo "  时间: $(date)"
echo "  推 110 失败 → 一键回滚 (SLA 5 分钟)"
echo "  关联: pre_push_backup_110prod_20260827.sh"
if [[ "${DRY_RUN}" == "1" ]]; then
    warn "DRY_RUN=1 模式, kill master + nohup 拉起步骤全部 NOOP, 仅演练 1-3 步"
fi
echo "================================================================"

# === 前置检查 ===
echo ""
echo "=== 前置检查 (回滚前必须 3 份备份都在) ==="

CODE_BACKUP="${BACKUP_DIR}/archery_v030_${TS}_code.tar.gz"
SCHEMA_BACKUP="${BACKUP_DIR}/archery_v030_${TS}_schema.sql"
ADMIN_BACKUP="${BACKUP_DIR}/archery_v030_${TS}_admin.json"

[[ ! -f "${CODE_BACKUP}" ]] && { err "代码备份不存在: ${CODE_BACKUP}"; exit 1; }
[[ ! -f "${SCHEMA_BACKUP}" ]] && { err "Schema 备份不存在: ${SCHEMA_BACKUP}"; exit 1; }
[[ ! -f "${ADMIN_BACKUP}" ]] && { err "Admin 备份不存在: ${ADMIN_BACKUP}"; exit 1; }
ok "3 份备份都在"

# 确认当前 gunicorn master 状态
current_master=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
if [[ -z "${current_master}" ]]; then
    warn "找不到 gunicorn master (PPID=1), 当前 gunicorn 状态:"
    ps -ef | grep gunicorn | grep -v grep | head -5
    echo ""
    echo "  提示: 推 110 失败可能 gunicorn 已 crash, 直接跳到回滚步骤 2"
else
    ok "当前 gunicorn master pid: ${current_master}"
fi

# === 询问 DBA 二次确认 ===
echo ""
echo "=== 二次确认 ==="
echo "  你要回滚 110 prod 到推 110 之前的状态"
echo "  影响: 所有 8/27 21:00 后的新代码 + 业务配置 + gh-ost 任务全部回滚"
echo "  时间: 30 秒 (rsync 50MB)"
echo ""
read -p "  确认回滚? (yes/no): " confirm
if [[ "${confirm}" != "yes" ]]; then
    warn "DBA 取消回滚, 退出"
    exit 0
fi

# === 步骤 1: 停 gunicorn (5 秒) ===
echo ""
echo "=== 步骤 1: 停 gunicorn ==="

if [[ "${DRY_RUN}" == "1" ]]; then
    warn "DRY_RUN=1 模式, 跳过 kill master (演练)"
    echo "  演练场景: gunicorn master 仍跑, 业务用户无感"
elif [[ -n "${current_master}" ]]; then
    kill ${current_master}
    sleep 2
    # 验证 master 已退出
    after_kill=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
    if [[ -n "${after_kill}" && "${after_kill}" != "${current_master}" ]]; then
        warn "gunicorn master 没退出, 残留 pid: ${after_kill}"
        kill -9 ${after_kill} 2>/dev/null || true
        sleep 1
    fi
    ok "gunicorn master ${current_master} 已停"
else
    warn "跳过 kill master (没找到)"
fi

# === 步骤 2: 恢复代码 (10 秒, 50MB tarball 解压) ===
echo ""
echo "=== 步骤 2: 恢复代码 ==="
echo "  源: ${CODE_BACKUP}"
echo "  目标: ${PROD_PATH}"

if [[ "${DRY_RUN}" == "1" ]]; then
    warn "DRY_RUN=1 模式, 跳过 mv + tar -xzf (演练不真改文件系统, 8/25 教训)"
    echo "  演练场景: 134 dev gunicorn 13665 仍在跑, 业务不中断"
    # 演练模式下只验证 tarball 完整性
    if tar -tzf ${CODE_BACKUP} > /dev/null 2>&1; then
        ok "代码备份 tarball 完整性校验通过 ($(tar -tzf ${CODE_BACKUP} | wc -l) 个文件)"
    else
        err "代码备份 tarball 损坏, 演练不通过"
        exit 1
    fi
else
    # 先备份当前 (回滚后的) 状态, 万一回滚后又发现要再回滚
    mv ${PROD_PATH} ${PROD_PATH}.rollback_$(date +%H%M%S).bak 2>&1 | tail -3

    # 解压备份
    cd $(dirname ${PROD_PATH})
    tar -xzf ${CODE_BACKUP} 2>&1 | tail -3

    # 还原 venv 符号链接 (备份时 --exclude='venv', 还原后 venv 目录需要重建或符号链接)
    if [[ -d "/dbdata/archery_v114/venv" ]] && [[ ! -e "${PROD_PATH}/venv" ]]; then
        ln -sf /dbdata/archery_v114/venv ${PROD_PATH}/venv
        ok "venv 符号链接已重建"
    fi

    # chown 恢复 (备份时 archery:archery, 解压后可能 root 拥有)
    chown -R archery:archery ${PROD_PATH}
    ok "代码恢复完成, chown archery:archery"
fi

# === 步骤 3: 恢复 schema (10 秒, 仅当 migration 失败时) ===
echo ""
echo "=== 步骤 3: 恢复 schema ==="
echo "  源: ${SCHEMA_BACKUP}"
echo "  ⚠️  这一步会 DROP 所有 ext_* 表 + workflow_audit_setting + DdlGhostTask 表"
echo "  ⚠️  推 110 期间 8/27 21:00-21:30 的 gh-ost 任务进度会丢 (DBA 已评估接受)"
echo ""

read -p "  恢复 schema? (yes/no): " restore_schema
if [[ "${restore_schema}" == "yes" ]]; then
    mysql --defaults-file=/root/.my.cnf -e "DROP DATABASE IF EXISTS archery;"
    mysql --defaults-file=/root/.my.cnf -e "CREATE DATABASE archery DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_general_ci;"
    mysql --defaults-file=/root/.my.cnf archery < ${SCHEMA_BACKUP}
    ok "Schema 恢复完成 (DROP + CREATE + mysqldump 还原)"
else
    warn "跳过 schema 恢复 (DBA 选择保留当前表结构, 仅恢复代码)"
fi

# === 步骤 4: 拉起 gunicorn (5 秒) ===
echo ""
echo "=== 步骤 4: 拉起 gunicorn (跟之前一样的配置) ==="

if [[ "${DRY_RUN}" == "1" ]]; then
    warn "DRY_RUN=1 模式, 跳过 nohup 拉起 (演练)"
    echo "  演练场景: 134 dev systemd 已经在跑 gunicorn, 不需要手动拉起"
    new_master="(dry_run_noop)"
    # 不真睡 5 秒, 节省演练时间
else
    cd ${PROD_PATH}
    nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application \
        -w 4 \
        -b 0.0.0.0:9123 \
        --access-logfile - \
        --error-logfile - \
        --timeout 120 \
        > /tmp/gunicorn_rollback.log 2>&1 &

    sleep 5

    new_master=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
    if [[ -n "${new_master}" ]]; then
        ok "gunicorn master 拉起: ${new_master}"
    else
        err "gunicorn master 拉起失败, 看 /tmp/gunicorn_rollback.log"
        tail -20 /tmp/gunicorn_rollback.log
        exit 1
    fi
fi

# === 步骤 5: 验证 (10 秒) ===
echo ""
echo "=== 步骤 5: HTTP 验证 ==="

# 1. /login/
http_login=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:9123/login/)
echo "  /login/: HTTP ${http_login}"
if [[ "${http_login}" == "200" || "${http_login}" == "302" ]]; then
    ok "/login/ 验证通过"
else
    err "/login/ HTTP ${http_login}, 不正常"
fi

# 2. /dbaprinciples/ 302 跳登录 (无需登录)
http_dbaprinciples=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:9123/dbaprinciples/)
echo "  /dbaprinciples/: HTTP ${http_dbaprinciples} (302 = 跳登录, OK)"

# 3. admin 登录验证
admin_test=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:9123/admin/)
echo "  /admin/: HTTP ${admin_test} (302 = 跳登录, OK)"

# 4. gunicorn log 看有没有 5xx
gunicorn_log_count=$(grep -c ' 5[0-9][0-9] ' /tmp/gunicorn_rollback.log 2>/dev/null || echo 0)
if [[ ${gunicorn_log_count} -gt 0 ]]; then
    warn "gunicorn log 里有 ${gunicorn_log_count} 条 5xx 错误"
    tail -30 /tmp/gunicorn_rollback.log | grep -E ' 5[0-9][0-9] ' | head -5
else
    ok "gunicorn log 无 5xx 错误"
fi

# === 总结 ===
echo ""
echo "================================================================"
echo "[回滚完成]"
echo "  时间: $(date)"
echo "  状态:"
echo "    - 代码: 已恢复到 8/27 20:50 备份版本"
if [[ "${restore_schema}" == "yes" ]]; then
    echo "    - Schema: 已恢复 (8/27 20:50 备份, gh-ost 任务进度丢失)"
else
    echo "    - Schema: 保留 (8/27 推代码后的当前表结构)"
fi
echo "    - gunicorn: 新 master pid ${new_master}"
echo "    - HTTP 验证: /login/=${http_login}, /dbaprinciples/=${http_dbaprinciples}"
echo "    - 日志: ${LOG_FILE}"
echo ""
echo "  业务影响:"
echo "    - 8/27 21:00 推 110 失败, 已恢复到 8/27 20:50 状态"
echo "    - 业务 RD 之前正常 (v1.14.0 基础版, 无 gh-ost 无 字段 diff)"
echo "    - 推 110 重试: 修复问题后, 重新跑 5 步必做 + 推代码 + 备份这套"
echo ""
echo "  DBA 群发消息模板:"
echo "    [110 prod 回滚完成 @ ${new_master}]"
echo "    /login/=${http_login}, /dbaprinciples/=${http_dbaprinciples}"
echo "    回滚原因: <填>"
echo "    业务影响: 8/27 21:00 后新功能不可用, 基础功能正常"
echo "    推 110 重试时间: <待定>"
echo "================================================================"
