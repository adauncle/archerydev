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

shadow_out=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT GROUP_CONCAT(table_name SEPARATOR ', ') FROM information_schema.tables WHERE table_schema = 'archery' AND (table_name LIKE '%_gho' OR table_name LIKE '%_del' OR table_name LIKE '%_ghc');")
if [[ -z "$shadow_out" || "$shadow_out" == "NULL" ]]; then
    ok "影子表 0 张, 不需要清理"
else
    warn "发现影子表: $shadow_out"
    echo "  ⚠️  DANGER: 要 DROP 这些表吗? 先跟 DBA 二次确认"
    read -p "  确认要 DROP? (yes/no): " drop_confirm
    if [[ "$drop_confirm" == "yes" ]]; then
        for t in $(echo "$shadow_out" | tr ',' ' '); do
            echo "  DROP TABLE $t"
            mysql --defaults-file=/root/.my.cnf -D archery -e "DROP TABLE IF EXISTS \`$t\`;"
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
flow_out=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT GROUP_CONCAT(name, '=', audit_auth_groups SEPARATOR ' | ') FROM ext_approval_flow;")
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
sqladvisor_current=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT value FROM sql_config WHERE item='sqladvisor';" 2>/dev/null)
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
  mysql --defaults-file=/root/.my.cnf -D archery -e "
UPDATE sql_config SET value = '' WHERE item = 'sqladvisor';
"
  ok "sqladvisor value 已清空 (id=1940, len 0)"
else
  ok "sqladvisor item value 已为空 (无需操作)"
fi

# 验证
sqladvisor_after=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT LENGTH(value) FROM sql_config WHERE item='sqladvisor';" 2>/dev/null)
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
soar_current=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT value FROM sql_config WHERE item='soar';" 2>/dev/null)
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
  mysql --defaults-file=/root/.my.cnf -D archery -e "
UPDATE sql_config SET value = '' WHERE item = 'soar';
"
  ok "soar value 已清空 (id=1941, len 0)"
else
  ok "soar item value 已为空 (无需操作)"
fi

# 验证
soar_after=$(mysql --defaults-file=/root/.my.cnf -D archery -N -e "SELECT LENGTH(value) FROM sql_config WHERE item='soar';" 2>/dev/null)
echo ""
echo "验证: soar value_len=${soar_after} (期望 0)"

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

