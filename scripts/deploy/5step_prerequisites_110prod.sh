#!/bin/bash
# 5step_prerequisites_110prod.sh — 推 110 prod 5 步必做 (在 110 prod 上直接跑)
#
# ⚠️  本脚本是 110 prod 内部命令清单, 不通过 sshpass 远程调用
# ⚠️  跑法: ssh 登 110 prod → bash /tmp/5step_prerequisites_110prod.sh
# ⚠️  不要在 134 dev / Windows 上跑
#
# 5 步:
# 1. log dir chown + gh_ost 子目录
# 2. sock 清理
# 3. 影子表清理 (查询 + 可选 DROP, 110 prod 应该是 0 张)
# 4. 凭据重加密 (DBA 手动, 脚本不自动改)
# 5. fix_approval_flow_3level (idempotent)
#
# 跟 runbook `docs/runbooks/2026-08-17_push-v030b-to-110prod.md` 阶段 2 一一对应

PROD_PATH="/dbdata/archery_v114_c9236a0"

# 8/25 教训固化: 134 dev 演练时 .my.cnf 不在 /root, 在 /etc/archery/
#                加 MY_CNF env var 让 DBA 演练时覆盖
#                8/06 教训: 134 dev 真凭据在 /etc/archery/, 推 110 当天用 /root/.my.cnf
MY_CNF="${MY_CNF:-/root/.my.cnf}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
err() { echo -e "${RED}[ERR]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo "================================================================"
echo "5step_prerequisites_110prod.sh (在 110 prod 内部跑)"
echo "  时间: $(date)"
echo "  这 5 步都 idempotent, 推 110 当天可以重复跑"
echo "================================================================"

# === 步骤 1: log dir chown + gh_ost 子目录 ===
echo ""
echo "=== 步骤 1: log dir chown + gh_ost 子目录 ==="
echo "目的: gh-ost 跑起来后日志能写, 不用 root 权限"
echo ""

mkdir -p /var/log/archery/gh_ost
chown -R archery:archery /var/log/archery/
chmod 755 /var/log/archery/gh_ost

echo "验证:"
ls_out=$(ls -ld /var/log/archery/ /var/log/archery/gh_ost/ 2>&1)
echo "  $ls_out"
if echo "$ls_out" | grep -q "archery archery"; then
    ok "步骤 1 完成 (log dir 权属 archery:archery)"
else
    err "步骤 1 失败: $ls_out"
fi

# === 步骤 2: sock 清理 ===
echo ""
echo "=== 步骤 2: sock 清理 ==="
echo "目的: 防止 gh-ost 启动时 'address already in use'"
echo ""

pkill -9 -f gh-ost 2>/dev/null || true  # 110 prod 没跑过 gh-ost, 应该是 noop
sleep 1
rm -f /tmp/gh-ost.*.sock 2>/dev/null || true  # 110 prod 没残留, 应该是 noop

echo "验证:"
sock_out=$(ls -la /tmp/gh-ost.*.sock 2>&1 | head -5)
echo "  $sock_out"
if echo "$sock_out" | grep -q "No such file"; then
    ok "步骤 2 完成 (无 sock 残留)"
else
    warn "步骤 2 仍有 sock: $sock_out"
fi

# === 步骤 3: 影子表清理 ===
echo ""
echo "=== 步骤 3: 影子表清理 ==="
echo "目的: gh-ost 失败残留的 _gho/_del/_ghc 影子表清理"
echo "  ⚠️  110 prod 没跑过 gh-ost, 应该是 0 张"
echo "  ⚠️  如果有残留, DROP 前要跟 DBA 二次确认 (数据可能有用)"
echo ""

shadow_out=$(mysql --defaults-file=${MY_CNF} -D archery -N -e "SELECT GROUP_CONCAT(table_name SEPARATOR ', ') FROM information_schema.tables WHERE table_schema = 'archery' AND (table_name LIKE '%_gho' OR table_name LIKE '%_del' OR table_name LIKE '%_ghc');")
if [[ -z "$shadow_out" || "$shadow_out" == "NULL" ]]; then
    ok "影子表 0 张, 不需要清理"
else
    warn "发现影子表: $shadow_out"
    echo "  ⚠️  DANGER: 要 DROP 这些表吗? 先跟 DBA 二次确认"
    read -p "  确认要 DROP? (yes/no): " drop_confirm
    if [[ "$drop_confirm" == "yes" ]]; then
        for t in $(echo "$shadow_out" | tr ',' ' '); do
            echo "  DROP TABLE $t"
            mysql --defaults-file=${MY_CNF} -D archery -e "DROP TABLE IF EXISTS \`$t\`;"
        done
        ok "影子表已 DROP"
    else
        warn "用户取消 DROP, 保留影子表"
    fi
fi

# === 步骤 4: 凭据重加密 (DBA 手动) ===
echo ""
echo "=== 步骤 4: 凭据重加密 (DBA 手动, 不脚本化) ==="
echo "原因: Archery 上游 instance.user / password 是 mirage EncryptedCharField"
echo "      8/06 教训: K1 密文 K2 解不开导致 MySQL 1045"
echo "      推 110 时 DBA 必须**手动**在 admin 后台重新保存 instance, 触发 K2 重加密"
echo ""
echo "  操作步骤:"
echo "  1. 浏览器登录 110 prod admin: https://prodarchery.ahggwl.com:9123/admin/"
echo "  2. 进入 SQL_INSTANCE 模型"
echo "  3. 逐个点开 instance, 重新输入 user / password (从 /etc/archery/dbops_password 读)"
echo "  4. 保存 (Django 自动用当前 SECRET_KEY 重新加密)"
echo "  5. 验证: Django shell 跑 instance.get_username_password() 测连"
echo ""
echo "  ⚠️  禁止脚本化: 踩生产 + 涉及业务凭据, 100% DBA 手动"
warn "步骤 4 需要 DBA 手动, 脚本不自动跑"
echo ""
read -p "DBA 已完成步骤 4? (yes/no): " dba_confirm
if [[ "$dba_confirm" == "yes" ]]; then
    ok "DBA 确认步骤 4 已完成"
else
    warn "DBA 未完成步骤 4, 推 110 之前必须完成"
fi

# === 步骤 5: fix_approval_flow_3level ===
echo ""
echo "=== 步骤 5: fix_approval_flow_3level (idempotent) ==="
echo "目的: 8/11 commit d5f88d1 加的 management command"
echo "      把 ext_approval_flow 3 个 flow 的 audit_auth_groups 改成 '14,15,3'"
echo "      110 prod 当前 ext_approval_flow 是空表, 跑这步会创建 3 个 flow"
echo ""
echo "  ⚠️  重要: 这个 command 是 8/11 commit 加的, 110 prod 部署的 v0.2.0 还没这个 command"
echo "  ⚠️  必须先跑阶段 3 (推代码) 把这个 command 部署上来, 再跑这步"
echo "  ⚠️  如果是预演练 (8/17), 这步会 Unknown command, 不阻塞主流程"
echo ""

cd ${PROD_PATH}
# 检查 command 是否存在
if sudo -u archery venv/bin/python manage.py help 2>&1 | grep -q fix_approval_flow_3level; then
    sudo -u archery venv/bin/python manage.py fix_approval_flow_3level 2>&1
    cmd_exit=$?
else
    warn "fix_approval_flow_3level command 还没部署 (预期: 预演练 / 推 110 阶段 3 后再跑)"
    cmd_exit=0  # 预演练不算失败
fi

echo ""
echo "验证:"
flow_out=$(mysql --defaults-file=${MY_CNF} -D archery -N -e "SELECT GROUP_CONCAT(name, '=', audit_auth_groups SEPARATOR ' | ') FROM ext_approval_flow;")
echo "  ext_approval_flow 数据: $flow_out"
if [[ -n "$flow_out" && "$flow_out" != "NULL" ]] && echo "$flow_out" | grep -q "14,15,3"; then
    ok "步骤 5 完成 (3 flow 都是 14,15,3)"
elif [[ "$cmd_exit" != "0" ]]; then
    err "步骤 5 失败: $flow_out"
else
    warn "步骤 5 跳过 (command 没部署, 推 110 阶段 3 后重跑)"
fi

echo ""
echo "================================================================"
echo "[5 步必做完成]"
echo "  110 prod 当前状态跟 runbook 摸底报告应该一致"
echo "  下一步: 推代码 (阶段 3) + restart gunicorn + 烟测 (阶段 4)"
echo "================================================================"

# === 步骤 6: 清空 sqladvisor 历史配置 (8/18 用户报 bug) ===
echo ""
echo "=== 步骤 6: 清空 110 prod sqladvisor 历史配置 (8/18 bug 修复) ==="
echo "目的: 8/18 17:47 业务用户点 SQL 优化报 500 错"
echo "      '[Errno 2] No such file or directory: /opt/archery/src/plugins/sqladvisor'"
echo "      110 prod v1.10.0 docker 时代 admin 后台配的 sqladvisor 路径"
echo "      8/05 切 v1.14.0 裸机后没改, 二进制也没装"
echo "      修法: 清空 sqladvisor item value, 业务用户点 SQL 优化返 '请配置' 友好提示"
echo ""
echo "  ⚠️  重要: 这是历史 bug, 跟推 v0.3.0-beta 无关, 但推 110 当天顺手清空"
echo "  ⚠️  真实修复 (装 sqladvisor 二进制 + 改配置) DBA 推完后手动做, 不在本脚本范围"
echo ""

# 备份当前 value (用于 rollback 准备)
sqladvisor_current=$(mysql --defaults-file=${MY_CNF} -D archery -N -e "SELECT value FROM sql_config WHERE item='sqladvisor';" 2>/dev/null)
if [[ -n "${sqladvisor_current}" ]]; then
  warn "sqladvisor item 当前有 value (len=${#sqladvisor_current}), 准备清空"
  echo "  原 value (加密): ${sqladvisor_current}"
  # 备份到 /tmp
  cat > /tmp/sqladvisor_backup_110prod_value.txt <<EOF
110 prod sqladvisor value (清空前备份)
timestamp: $(date '+%Y-%m-%d %H:%M:%S')
item: sqladvisor
value (加密): ${sqladvisor_current}
rollback: 在 admin 后台 /admin/sql/config/<id>/change/ 把 value 粘回去
EOF
  echo "  备份写到: /tmp/sqladvisor_backup_110prod_value.txt"

  # 清空
  mysql --defaults-file=${MY_CNF} -D archery -e "
UPDATE sql_config SET value = '' WHERE item = 'sqladvisor';
"
  ok "sqladvisor value 已清空 (id=1940, len 0)"
else
  ok "sqladvisor item value 已为空 (无需操作)"
fi

# 验证
sqladvisor_after=$(mysql --defaults-file=${MY_CNF} -D archery -N -e "SELECT LENGTH(value) FROM sql_config WHERE item='sqladvisor';" 2>/dev/null)
echo ""
echo "验证: sqladvisor value_len=${sqladvisor_after} (期望 0)"

# === 步骤 7: 清空 soar 历史配置 (8/19 用户报 bug) ===
echo ""
echo "=== 步骤 7: 清空 110 prod soar 历史配置 (8/19 bug 修复) ==="
echo "目的: 8/19 09:32 业务用户点 SOAR 区域报 500 错"
echo "      '[Errno 2] No such file or directory: /opt/archery/src/plugins/soar'"
echo "      110 prod v1.10.0 docker 时代 admin 后台配的 soar 路径"
echo "      8/05 切 v1.14.0 裸机后没改, 二进制也没装"
echo "      修法: 清空 soar item value, 业务用户点 SOAR 返 '请配置' 友好提示"
echo ""
echo "  ⚠️  重要: 跟 sqladvisor 同根因, 推 110 当天顺手清空"
echo "  ⚠️  真实修复 (装 soar 二进制 + 改配置) DBA 推完后手动做, 不在本脚本范围"
echo ""

# 备份当前 value
soar_current=$(mysql --defaults-file=${MY_CNF} -D archery -N -e "SELECT value FROM sql_config WHERE item='soar';" 2>/dev/null)
if [[ -n "${soar_current}" ]]; then
  warn "soar item 当前有 value (len=${#soar_current}), 准备清空"
  echo "  原 value (加密): ${soar_current}"
  # 备份到 /tmp
  cat > /tmp/soar_backup_110prod_value.txt <<EOF
110 prod soar value (清空前备份)
timestamp: $(date '+%Y-%m-%d %H:%M:%S')
item: soar
value (加密): ${soar_current}
rollback: 在 admin 后台 /admin/sql/config/<id>/change/ 把 value 粘回去
EOF
  echo "  备份写到: /tmp/soar_backup_110prod_value.txt"

  # 清空
  mysql --defaults-file=${MY_CNF} -D archery -e "
UPDATE sql_config SET value = '' WHERE item = 'soar';
"
  ok "soar value 已清空 (id=1941, len 0)"
else
  ok "soar item value 已为空 (无需操作)"
fi

# 验证
soar_after=$(mysql --defaults-file=${MY_CNF} -D archery -N -e "SELECT LENGTH(value) FROM sql_config WHERE item='soar';" 2>/dev/null)
echo ""
echo "验证: soar value_len=${soar_after} (期望 0)"

# === 步骤 8: gh-ost / soar / sqladvisor 二进制装 (8/24 摸底 110 prod 没装, 8/25 必装) ===
echo ""
echo "=== 步骤 8: gh-ost / soar / sqladvisor 二进制装 ==="
echo "目的: 8/24 摸底 110 prod 没装这些工具, 推 110 前必装"
echo "      gh-ost v1.1.10 (跟 134 dev 一致) / soar 14MB / sqladvisor 455KB"
echo "      8/19 套路: 装到 /opt/archery/bin/ (archery user 拥有) + /usr/local/bin/ symlink (代码默认路径能找到)"
echo "      8/18 教训: 别装 /usr/local/bin/ (root 拥有 755, gunicorn archery user 跑不了)"
echo ""

# 8.1 gh-ost (8/24 已经从 134 dev sftp 装过, idempotent 检查)
echo "8.1 gh-ost:"
if [[ -x /opt/archery/bin/gh-ost ]] && /opt/archery/bin/gh-ost --version 2>&1 | grep -q "1.1.10"; then
    ok "gh-ost 1.1.10 已装 (8/24 完成)"
else
    warn "gh-ost 没装或版本不对, 装 (走 8/24 套路, 从 134 dev sftp)"
    echo "  ⚠️  这步需要 134 dev 可达, 推 110 当天如果 134 dev 不可达, 手动:"
    echo "     1. 134 dev 端: scp /usr/local/bin/gh-ost archery@110:/tmp/"
    echo "     2. 110 prod 端: cp /tmp/gh-ost /opt/archery/bin/gh-ost && chown archery:archery && chmod 755"
    echo "     3. ln -sf /opt/archery/bin/gh-ost /usr/local/bin/gh-ost"
    # 实际装 (如果 /tmp/gh-ost 存在就用, 否则从 134 dev 拉)
    if [[ -f /tmp/gh-ost ]]; then
        cp /tmp/gh-ost /opt/archery/bin/gh-ost
        chown archery:archery /opt/archery/bin/gh-ost
        chmod 755 /opt/archery/bin/gh-ost
        ln -sf /opt/archery/bin/gh-ost /usr/local/bin/gh-ost
        ok "gh-ost 已从 /tmp/gh-ost 装好"
    else
        err "/tmp/gh-ost 不存在, 需要 DBA 手动装 (见上面命令)"
    fi
fi
# symlink 幂等
ln -sf /opt/archery/bin/gh-ost /usr/local/bin/gh-ost 2>/dev/null || true

# 8.2 soar (8/19 已装, idempotent 检查)
echo ""
echo "8.2 soar:"
if [[ -x /opt/archery/bin/soar ]]; then
    ok "soar 已装 (8/19 完成)"
else
    warn "soar 没装, DBA 手动装:"
    echo "     cp /tmp/soar /opt/archery/bin/soar"
    echo "     chown archery:archery /opt/archery/bin/soar"
    echo "     chmod 755 /opt/archery/bin/soar"
    err "soar 装好前, 业务用户点 SQLAdvisor 区域会失败"
fi

# 8.3 sqladvisor (8/18 装过, 工具已死, 但路径得有)
echo ""
echo "8.3 sqladvisor:"
if [[ -x /opt/archery/bin/sqladvisor ]]; then
    ok "sqladvisor 已装 (8/18 完成, 工具已死但路径得有, 避免 500)"
else
    warn "sqladvisor 没装, DBA 手动装 (8/18 docker overlay 复用 455KB 版)"
fi

# === 步骤 9: features.py 5.7 patch (8/17 摸底: 110 prod MySQL 5.7, 134 dev 8.0) ===
echo ""
echo "=== 步骤 9: features.py 5.7 patch (110 prod MySQL 5.7 vs 134 dev 8.0) ==="
echo "目的: 8/17 摸底发现 110 prod MySQL 5.7.44, 134 dev 8.0.22"
echo "      5.7 没有 performance_schema.metadata_locks 这个 view"
echo "      Archery 8.x 跟 5.7 兼容, 但 features.py 要 patch"
echo "      8/24 教训: gh-ost 5.7/8.0 行为差异是 ENGINE=InnoDB trigger 5.7 也接受"
echo ""

# 检查 MySQL 版本
mysql_version=$(mysql --defaults-file=${MY_CNF} -N -e "SELECT VERSION();" 2>&1 | head -1)
echo "  当前 MySQL 版本: ${mysql_version}"

# 5.7 特征字符串
if echo "${mysql_version}" | grep -q "5.7"; then
    if [[ -f "${PROD_PATH}/sql/engines/mysql/features.py" ]]; then
        if grep -q "metadata_locks" "${PROD_PATH}/sql/engines/mysql/features.py" 2>/dev/null; then
            warn "features.py 5.7 patch 还没打 (可能有 metadata_locks 引用)"
            echo "  ⚠️  5.7 没这个 view, 推 110 必打 patch"
            echo "  ⚠️  8/17 摸底已确认 5.7 patch 在 sql/engines/mysql/features.py"
            echo "  ⚠️  5.7 patch 内容: 把 metadata_locks 引用改成 try/except, 5.7 跳过这步"
            # 不在 5 步必做里自动改, 由推代码阶段 (跟 8/17 摸底 runbook 走) 处理
        else
            ok "features.py 5.7 patch 已打 (8/17 摸底前已处理)"
        fi
    else
        warn "features.py 不存在: ${PROD_PATH}/sql/engines/mysql/features.py"
    fi
elif echo "${mysql_version}" | grep -q "8.0"; then
    ok "MySQL 8.0, 5.7 patch 不需要 (代码原生 8.0 兼容)"
else
    warn "未识别的 MySQL 版本: ${mysql_version}"
fi

# === 步骤 10: gh-ost 4 perm 预创建 (8/13 commit 0004 走 migrate, 但推 110 后才跑) ===
echo ""
echo "=== 步骤 10: gh-ost 4 perm 预创建 (8/13 5 步必做流程) ==="
echo "目的: 8/13 commit 0004 创建 4 个 perm: view/upload/change/delete ddlghosttask"
echo "      推 110 跑 migrate 后, 5 步必做 idempotent 检查这 4 个 perm 存在"
echo "      如果不存在, 手动创建 (DBA 必做)"
echo ""

if cd ${PROD_PATH} && sudo -u archery venv/bin/python manage.py shell -c "
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from sql.extensions.ddl_gh_ost.models import DdlGhostTask
ct = ContentType.objects.get_for_model(DdlGhostTask)
for codename, name in [
    ('view_ddlghosttask', 'Can view ddl ghost task'),
    ('add_ddlghosttask', 'Can add ddl ghost task'),
    ('change_ddlghosttask', 'Can change ddl ghost task'),
    ('delete_ddlghosttask', 'Can delete ddl ghost task'),
]:
    p, created = Permission.objects.get_or_create(codename=codename, content_type=ct, defaults={'name': name})
    print(f'  {codename}: {\"已存在\" if not created else \"已创建\"}')
" 2>&1 | tail -10; then
    ok "步骤 10 完成 (4 perm 已存在/已创建)"
else
    warn "步骤 10 跳过 (migrate 还没跑, 推 110 后再跑)"
fi

# === 步骤 11: 8/24 6 bug fix verify (推代码后跑, 这里只 dry run 检查) ===
echo ""
echo "=== 步骤 11: 8/24 6 bug fix verify (dry run, 推代码后跑) ==="
echo "目的: 推代码后, 验证 6 个 bug fix 都到位"
echo "      8/24 commit 列表: a41c4d0 / 9d66064 / eaf9853 / e669567 / 0b62856 / 76d48cc / 324a53a"
echo "      dry run 只看代码文件存在, 真验在步骤 13 之后"
echo ""

# 检查 7 个文件 mtime 是不是 8/24 之后
files_to_check=(
    "${PROD_PATH}/sql/extensions/audit_drivers/configurable_auditor.py"
    "${PROD_PATH}/sql/extensions/ddl_gh_ost/services/precheck.py"
    "${PROD_PATH}/sql/utils/workflow_audit.py"
    "${PROD_PATH}/sql/extensions/ddl_gh_ost/services/column_diff.py"
    "${PROD_PATH}/sql/templates/detail.html"
    "${PROD_PATH}/sql/sql_workflow.py"
    "${PROD_PATH}/sql/views.py"
)
all_ok=1
for f in "${files_to_check[@]}"; do
    if [[ ! -f "$f" ]]; then
        warn "  缺失: $f"
        all_ok=0
    else
        mtime=$(stat -c '%y' "$f" | cut -d. -f1)
        echo "  OK: $(basename $f) mtime=$mtime"
    fi
done
if [[ ${all_ok} == 1 ]]; then
    ok "步骤 11 通过 (7 个文件都在)"
else
    err "步骤 11 有文件缺失, 推代码阶段需补"
fi

# === 步骤 12: gunicorn master pid 记录 (推 110 必知, kill 它) ===
echo ""
echo "=== 步骤 12: gunicorn master pid 记录 (推 110 必 kill 它) ==="
master_pid=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
if [[ -n "${master_pid}" ]]; then
    ok "当前 gunicorn master pid: ${master_pid}"
    echo "  启动时间: $(ps -o lstart= -p ${master_pid} 2>/dev/null)"
    echo "  推 110 当天 kill 命令: kill ${master_pid}"
    echo "  然后 8 步操作里 nohup 拉起新 master"
else
    warn "找不到 gunicorn master (PPID=1), 推 110 必查"
fi

echo ""

echo ""
# === 步骤 13: 部署 configurable_auditor.py 改动 + kill master 重启 (8/24 教训) ===
echo ""
echo "=== 步骤 13: 部署 configurable_auditor.py 改动 + kill master 重启 ==="
echo "目的: 8/24 修法 — ConfigurableAuditor 命中 policy 时走父类, 用 Archery 上游 WorkflowAuditSetting"
echo "      8/24 教训 — gunicorn HUP 不重载 Python 代码, 必须 kill master 让 systemd 拉起新进程"
echo "      推 110 时必须: 部署代码 + kill master + 提一条新工单验证 detail 页生效"
echo ""
echo "  ⚠️  必须在阶段 3 (推代码) 之后跑, 否则代码还没更新, 验证无意义"
echo "  ⚠️  110 prod gunicorn 是 archery user 手动启的 (没 systemd unit), kill 后需 DBA 手动 nohup 拉起"
echo ""

# 1. 确认代码已更新 (跟 8/24 134 dev 一致)
if grep -q "走父类, 用 Archery 上游 WorkflowAuditSetting" ${PROD_PATH}/sql/extensions/audit_drivers/configurable_auditor.py 2>/dev/null; then
    ok "configurable_auditor.py 已是 8/24 修法版"
else
    err "configurable_auditor.py 还是旧版, 请先推代码 (阶段 3) 再跑这步"
    echo "  期望: 命中 policy 时 return super().generate_audit_setting()"
    echo "  实际: $(grep -E 'audit_auth_groups|return AuditSetting' ${PROD_PATH}/sql/extensions/audit_drivers/configurable_auditor.py | head -3)"
    exit 1
fi

# 2. 找 110 prod 当前 gunicorn master pid (PPID=1 的那个是 master)
master_out=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
if [[ -z "${master_out}" ]]; then
    warn "找不到 gunicorn master (PPID=1 的那个), 110 prod 是手动启的"
    echo "  110 prod 当前所有 gunicorn 进程:"
    ps -ef | grep gunicorn | grep -v grep
    echo ""
    echo "  请 DBA 手动操作:"
    echo "    1. pkill -TERM -f gunicorn"
    echo "    2. cd ${PROD_PATH}"
    echo "    3. nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 &"
    echo "    4. 验证 curl -I http://172.20.2.110:9123/"
    exit 1
fi
echo "  当前 master pid: ${master_out}"

# 3. kill master
echo "  kill ${master_out} ..."
kill ${master_out}

# 4. 等新进程起来 (134 dev 有 systemd 自动拉, 110 prod 没有, DBA 手动)
sleep 3
new_master=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
if [[ -n "${new_master}" && "${new_master}" != "${master_out}" ]]; then
    ok "新 master pid: ${new_master} (旧 master ${master_out} 已退出)"
else
    warn "新 master 没自动起来, 110 prod 没 systemd unit, 需 DBA 手动 nohup"
    echo "  启动命令:"
    echo "    cd ${PROD_PATH}"
    echo "    nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 > /tmp/gunicorn.log 2>&1 &"
    echo "  启动后跑步骤 13 验证"
    exit 1
fi

# 5. 验证
echo ""
echo "验证 1: HTTP 健康检查"
http_out=$(curl -sI --max-time 5 http://127.0.0.1:9123/ 2>&1 | head -3)
echo "  ${http_out}"
if echo "${http_out}" | grep -q "200\|302"; then
    ok "HTTP 200/302, gunicorn alive"
else
    err "HTTP 不正常, 排查: 9123 端口 / 进程状态"
fi

echo ""
echo "验证 2 (DBA 必做): 提一条新 SQL 上线工单, detail 页审批流应跟 config/ 配一致"
echo "  8/24 教训: 提交页 (/group/auditors/) 走老接口 Audit.settings(), 容易显示对"
echo "              详情页 (/detail/<id>/) 走 ConfigurableAuditor.generate_audit_setting, 才是真测试路径"
echo "  验证步骤:"
echo "    1. 浏览器登 110 prod, 选 '测试组' / 任一 group_id"
echo "    2. SQL 上线提交页: 选 group → 选 instance → 选 db → 看 '审批流程' 应显示 config/ 配的级别"
echo "    3. 提交一条 ALTER 工单 (随便一句 ALTER ... DROP COLUMN xxx, 不会真跑)"
echo "    4. detail 页 '审批流' 区域: 应跟 config/ 配的级别一致 (不是 ext_approval_flow 配的)"
echo "  ⚠️  如果 detail 页跟 config/ 不一致 → gunicorn master 启动时间跟代码部署时间对不上, HUP 没生效 (8/24 教训)"
echo ""

echo "================================================================"
echo "[5 步必做脚本完整版: 步骤 1-13 全跑]"
echo "  推 110 必跑: 步骤 1-13 全过"
echo "  推 110 失败回滚: 跑 rollback_110prod_v030_20260827.sh"
echo "================================================================"


