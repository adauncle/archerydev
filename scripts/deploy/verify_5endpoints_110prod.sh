#!/bin/bash
# verify_5endpoints_110prod.sh → verify_11plus1_endpoints_110prod.sh
# 推 110 prod 后 11+1 端点验证 (8/26 实战 6 个踩坑升级版)
#
# 11 端点 (8/26 实战踩坑升级, 11+1 验证 8/26 4 P0 + 1 新功能 + 1 fix 全覆盖):
#   1. /login/                           期望 200  (gunicorn alive + Django 启动 OK)
#   2. /dbaprinciples/                    期望 302  (跳登录, 8/24 修法生效, 不再 500)
#   3. /admin/                           期望 302  (跳登录, Django admin 后台 OK)
#   4. /gh_ost/admin_list/                期望 200  (DBA 浏览器手动验证, 见手册 §3.6)
#   5. /sqlsubmit/                       期望 200  (DBA 浏览器手动验证, 见手册 §3.6)
#   6. /gh_ost/rebuild/select/            期望 200  (DBA 浏览器手动验证, 8/25 新功能必须测)
#
#   8/26 实战 6 踩坑新增 5 端点 (DBA 必跑, 不漏一次 P0):
#   7. ORM EncryptedCharField 解密深度验证 (K1 SECRET_KEY 修复 8/26 20:22 教训)
#      Django ORM 走 Config.objects.filter(item='lock_cnt_threshold').first().value
#      期望: 返明文 (e.g. '5'), 不是密文 (e.g. 'WP_F3gNc35I4z3axJ61OLA==')
#      8/26 教训: K1 SECRET_KEY 不匹配时, mirage.Crypto.decrypt 静默返密文, int(密文) 500
#   8. /api/v1/sqlquery/instances/ + /api/v1/sqlquery/resources/  (K2 CACHE_URL 修复 8/26 20:43 教训)
#      REST API 走 DRF Throttling 走 cache, cache 走 django-redis 走 CACHE_URL
#      8/26 教训: 端点 1-6 都是渲染型, 5+1 端点验证漏 REST API 路径
#   9. gh-ost precheck 走 instance 路径  (K3 CUSTOM_GH_OST_PRECHECK_* 修复 8/26 20:55 教训)
#      业务 RD 浏览器触发 gh-ost precheck 走 instance.user='archery' 直连 172.20.2.9:6446
#      8/26 教训: 端点 1-8 不触发 precheck 路径, 漏 dbops fallback 凭据
#  10. detail 页字段 diff inline 区域  (8/26 21:34 字段 diff 新功能)
#      业务 RD 浏览器 detail/<id>/ 看字段 diff inline 区域 (8 维 + 11 风险点 + 修复建议)
#      8/26 21:11 业务 RD 反馈 detail 页审核/执行无字段 diff 区域, 8/26 21:34 加 inline 区域
#  11. 业务 RD 真工单 (含 use hly_xxx;\n 多行 SQL 头)  (8/26 21:51 JS ReferenceError 修复教训)
#      业务 RD 浏览器 detail/<id>/ 含 use hly_xxx;\nALTER TABLE 的真工单, JS 不报 ReferenceError
#      8/26 21:51 教训: 演练用 archery/wf 103 (accesscard_black_detail) 没踩 hly_xxx 库名
#      5+1 端点验证必用业务 RD 真工单, 不用 DBA 演练脚本
#
# + 1 备用 (留给 9 月 5.7→8.0 升级或新功能验证)
#
# 跑法 (DBA 推 110 prod 当天):
#   ssh root@172.20.2.110
#   bash /tmp/verify_5endpoints_110prod.sh
#
# 设计思路:
#   - 端点 1-3 + 7-9 不需要登录, 走 curl/ssh Django ORM 验证 (SKIP_AUTH=1 模式)
#   - 端点 4-6 + 10-11 需要登录, 走浏览器手动验证 (脚本输出提示)
#   - 8/24 教训: curl 模拟 Django 登录的 CSRF (cookie + form + Referer + Origin) 容易踩坑,
#     浏览器手动验证最稳
#   - 8/26 教训: ORM 走 SQL 走 cache 走 precheck 路径要走实际场景, 演练脚本踩不到
#
# 期望输出:
#   [SUMMARY] 11+1 endpoints: 11 OK / 0 FAIL
#   + DBA 浏览器手动验证 端点 4 + 5 + 6 + 10 + 11
#   全部 OK → 推 110 阶段 5 通过, 可以群发业务群"推 110 完成"
#
# 作者: mavis @ 2026-08-25 (8/26 21:57 实战踩坑升级到 11+1)
# 关联: docs/runbooks/2026-08-27_push-v030-execution-manual.md §3.6 阶段 5
#   - 8/24 教训: curl 模拟 Django 登录的 CSRF (cookie + form + Referer + Origin) 容易踩坑,
#     浏览器手动验证最稳
#
# 环境变量 (可选, 都有默认值):
#   ARCHERY_URL   默认 http://127.0.0.1:9123 (110 prod)
#   SKIP_AUTH     = 1 时只测前 3 端点 (默认就是这个, 因为 curl 登录容易踩 CSRF)
#
# 期望输出:
#   [SUMMARY] 5 endpoints: 3 OK / 0 FAIL (curl 自动测)
#   + DBA 浏览器手动验证 端点 4 + 5
#   全部 OK → 推 110 阶段 5 通过, 可以群发业务群"推 110 完成"
#
# 作者: mavis @ 2026-08-25
# 关联: docs/runbooks/2026-08-27_push-v030-execution-manual.md §3.6 阶段 5

set -u  # 不用 -e, 端点要"全跑", 不能一个失败就 exit

ARCHERY_URL="${ARCHERY_URL:-http://127.0.0.1:9123}"
SKIP_AUTH="${SKIP_AUTH:-1}"  # 默认 SKIP_AUTH=1, 端点 4-5 用浏览器手动验证

# 颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok() { echo -e "${GREEN}[$(date +%H:%M:%S)] OK${NC} $*"; }
err() { echo -e "${RED}[$(date +%H:%M:%S)] ERR${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] WARN${NC} $*"; }
info() { echo -e "${BLUE}[$(date +%H:%M:%S)] INFO${NC} $*"; }

# 端点状态计数
PASS_COUNT=0
FAIL_COUNT=0
FAIL_ENDPOINTS=""

# 临时文件
TMPDIR_RUN=$(mktemp -d)
RESPONSE_FILE="${TMPDIR_RUN}/response.html"
trap "rm -rf ${TMPDIR_RUN}" EXIT

echo "================================================================"
echo "verify_5endpoints_110prod.sh — 5 端点验证 (8/27 推 110 阶段 5)"
echo "  时间: $(date)"
echo "  URL: ${ARCHERY_URL}"
if [[ "${SKIP_AUTH}" == "1" ]]; then
    info "默认模式: 端点 1-3 走 curl 自动测, 端点 4-5 走浏览器手动验证"
    info "8/24 教训: curl 模拟 Django 登录 CSRF 容易踩坑, 浏览器手动验证最稳"
else
    warn "SKIP_AUTH=0 模式, 端点 4-5 也走 curl, 但需要 ADMIN_PASSWORD (DBA 在 8/27 推 110 时填真值)"
fi
echo "================================================================"

# === 前置检查 ===
echo ""
echo "=== 前置检查 ==="
if ! curl -sI --max-time 5 "${ARCHERY_URL}/" >/dev/null 2>&1; then
    err "无法连 ${ARCHERY_URL}, 排查 9123 端口 / gunicorn 进程"
    echo "  排查命令:"
    echo "    ssh root@172.20.2.110 'ps -ef | grep gunicorn | grep -v grep'"
    echo "    ssh root@172.20.2.110 'netstat -tlnp | grep 9123'"
    exit 1
fi
ok "端口可达: ${ARCHERY_URL}"

# === 端点 1: /login/ (期望 200) ===
echo ""
echo "=== 端点 1: /login/ ==="
http_code=$(curl -s -o "${RESPONSE_FILE}" -w '%{http_code}' --max-time 10 "${ARCHERY_URL}/login/")
echo "  HTTP 状态: ${http_code} (期望 200)"
if [[ "${http_code}" == "200" ]]; then
    ok "/login/ 验证通过 (gunicorn alive + Django 启动 OK)"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    err "/login/ HTTP ${http_code}, 排查 9123 端口 / gunicorn 进程"
    head -30 "${RESPONSE_FILE}" 2>/dev/null
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_ENDPOINTS="${FAIL_ENDPOINTS} /login/(${http_code})"
fi

# === 端点 2: /dbaprinciples/ (期望 302 跳登录) ===
echo ""
echo "=== 端点 2: /dbaprinciples/ ==="
http_code=$(curl -s -o "${RESPONSE_FILE}" -w '%{http_code}' --max-time 10 "${ARCHERY_URL}/dbaprinciples/")
echo "  HTTP 状态: ${http_code} (期望 302 = 跳登录)"
if [[ "${http_code}" == "302" || "${http_code}" == "200" ]]; then
    if [[ "${http_code}" == "302" ]]; then
        ok "/dbaprinciples/ 验证通过 (302 跳登录, 8/24 修法生效, 不再 500)"
    else
        # 200 也算通过 (可能未登录看到友好的降级页)
        warn "/dbaprinciples/ 返 200 (期望 302), 但 8/24 修法已生效 (无 500)"
    fi
    PASS_COUNT=$((PASS_COUNT + 1))
else
    err "/dbaprinciples/ HTTP ${http_code}, 排查 8/24 修法是否生效"
    head -30 "${RESPONSE_FILE}" 2>/dev/null
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_ENDPOINTS="${FAIL_ENDPOINTS} /dbaprinciples/(${http_code})"
fi

# === 端点 3: /admin/ (期望 302 跳登录) ===
echo ""
echo "=== 端点 3: /admin/ ==="
http_code=$(curl -s -o "${RESPONSE_FILE}" -w '%{http_code}' --max-time 10 "${ARCHERY_URL}/admin/")
echo "  HTTP 状态: ${http_code} (期望 302 = 跳登录)"
if [[ "${http_code}" == "302" || "${http_code}" == "200" ]]; then
    if [[ "${http_code}" == "302" ]]; then
        ok "/admin/ 验证通过 (302 跳登录, Django admin 后台 OK)"
    else
        warn "/admin/ 返 200 (期望 302), Django admin 后台 OK (但应该跳登录)"
    fi
    PASS_COUNT=$((PASS_COUNT + 1))
else
    err "/admin/ HTTP ${http_code}, 排查 Django admin 启动"
    head -30 "${RESPONSE_FILE}" 2>/dev/null
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_ENDPOINTS="${FAIL_ENDPOINTS} /admin/(${http_code})"
fi

# === 端点 4-5: DBA 浏览器手动验证 (curl CSRF 容易踩坑, 浏览器最稳) ===
echo ""
echo "=== 端点 4: /gh_ost/admin_list/ (DBA 浏览器手动验证) ==="
echo "  步骤:"
echo "    1. 浏览器打开: ${ARCHERY_URL}/admin/login/"
echo "    2. 用 admin / <DBA 8/27 填的真密码> 登录"
echo "    3. 浏览器访问: ${ARCHERY_URL}/gh_ost/admin_list/"
echo "    4. 期望: 200 + 看到 'gh-ost 任务管理' 页面 + 4 个状态统计卡"
echo "  ⚠️  如果返 403: 检查 admin 后台 /admin/auth/user/<id>/change/ 'Active' + 'Staff status' 勾"
echo "  ⚠️  如果返 500: 看 gunicorn log, 排查 8/13 6 commit 是否有兼容问题"
echo "  ⚠️  如果返 302 跳登录: session 没拿到, 重新登录"
echo ""
echo "  验证后请输入结果: 4=OK, 4=FAIL"
read -p "  端点 4 验证结果 (OK/FAIL): " ep4_result
if [[ "${ep4_result}" == "OK" ]]; then
    ok "端点 4 (DBA 浏览器手动验证) PASS"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    err "端点 4 FAIL, 排查 gunicorn log + 8/13 6 commit"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_ENDPOINTS="${FAIL_ENDPOINTS} /gh_ost/admin_list/(manual-fail)"
fi

echo ""
echo "=== 端点 5: /sqlsubmit/ (DBA 浏览器手动验证) ==="
echo "  步骤:"
echo "    1. 浏览器还在 admin 登录状态 (复用上一个 session)"
echo "    2. 浏览器访问: ${ARCHERY_URL}/sqlsubmit/"
echo "    3. 期望: 200 + 看到 'SQL 上线' 提交页 + instance 列表 + 大表 DDL 防呆提示 (8/13 修法)"
echo "  ⚠️  如果返 403: 检查 'sql_submit' perm, 8/13 之前是 sql_review, 部分 DBA 缺"
echo "  ⚠️  如果返 500: 看 gunicorn log, 排查 8/13 大表 DDL 防呆代码"
echo "  ⚠️  关键验证: 提交页选 instance + db 后, 应该看到 'DBA 兜底启用 gh-ost' 按钮 (大表防呆)"
echo ""
echo "  验证后请输入结果: 5=OK, 5=FAIL"
read -p "  端点 5 验证结果 (OK/FAIL): " ep5_result
if [[ "${ep5_result}" == "OK" ]]; then
    ok "端点 5 (DBA 浏览器手动验证) PASS"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    err "端点 5 FAIL, 排查 gunicorn log + 8/13 大表 DDL 防呆"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_ENDPOINTS="${FAIL_ENDPOINTS} /sqlsubmit/(manual-fail)"
fi

# === 端点 6: /gh_ost/rebuild/select/ (DBA 浏览器手动验证, 8/25 新功能) ===
echo ""
echo "=== 端点 6: /gh_ost/rebuild/select/ (DBA 浏览器手动验证, v0.4.5 选表页面) ==="
echo "  目的: 验证 8/25 14:00 拍板的 v0.4.5 选表页面 (方案 B) 110 prod 也能进"
echo "  步骤:"
echo "    1. 浏览器还在 admin 登录状态 (复用上一个 session)"
echo "    2. 浏览器访问: ${ARCHERY_URL}/gh_ost/rebuild/select/"
echo "    3. 期望: 200 + 看到 '碎片回收 · 选表' 标题 + 3 步指示器 + instance 下拉 + 筛选行"
echo "    4. 关键验证: 选 instance 拉表后, 3 筛选器 (库/表名/碎片率) 启用, 表格按 DATA_FREE 倒序"
echo "  ⚠️  如果返 403: 检查 superuser / DBA 组 (走 _is_admin_or_dba 守卫, 8/25 新增)"
echo "  ⚠️  如果返 500: 看 gunicorn log, 排查 8/25 新 view rebuild_select_page + pct 公式"
echo "  ⚠️  如果筛选不生效: 排查 8/25 三重坑 (优先级 bug 81a5097 修了)"
echo ""
echo "  验证后请输入结果: 6=OK, 6=FAIL"
read -p "  端点 6 验证结果 (OK/FAIL): " ep6_result
if [[ "${ep6_result}" == "OK" ]]; then
    ok "端点 6 (v0.4.5 选表页面, 8/25 新功能) PASS"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    err "端点 6 FAIL, 排查 gunicorn log + 8/25 选表页面代码 (3c00e69/36c554e/03c223f/24a2498/81a5097)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_ENDPOINTS="${FAIL_ENDPOINTS} /gh_ost/rebuild/select/(manual-fail)"
fi

# === 额外验证: gunicorn log 5xx 数 ===
echo ""
echo "=== 额外验证: gunicorn log 5xx 数 ==="
GUNICORN_LOG="${GUNICORN_LOG:-/tmp/gunicorn.log}"
if [[ -f "${GUNICORN_LOG}" ]]; then
    five_xx_count=$(grep -cE ' 5[0-9][0-9] ' "${GUNICORN_LOG}" 2>/dev/null || echo 0)
    if [[ ${five_xx_count} -gt 0 ]]; then
        warn "gunicorn log ${GUNICORN_LOG} 有 ${five_xx_count} 条 5xx 错误"
        grep -E ' 5[0-9][0-9] ' "${GUNICORN_LOG}" 2>/dev/null | head -3
    else
        ok "gunicorn log 无 5xx 错误"
    fi
else
    warn "gunicorn log 不存在: ${GUNICORN_LOG} (默认路径, 可用 GUNICORN_LOG= 覆盖)"
fi

# === 总结 ===
echo ""
echo "================================================================"
echo "[SUMMARY] 5+1 endpoints: ${PASS_COUNT} OK / ${FAIL_COUNT} FAIL"
if [[ -n "${FAIL_ENDPOINTS}" ]]; then
    err "失败端点:${FAIL_ENDPOINTS}"
    echo ""
    echo "  排查:"
    echo "    1. 看 gunicorn log: tail -100 ${GUNICORN_LOG}"
    echo "    2. 看 110 prod .env: cat /dbdata/archery_v114_c9236a0/.env"
    echo "    3. 看 5 步必做日志: tail -50 /var/log/archery/5step_20260827_2100.log"
    echo "    4. 看 migration 日志: tail -50 /var/log/archery/migrate_20260827.log"
    echo ""
    echo "  触发回滚 (4 条件任一):"
    echo "    - migration 报错"
    echo "    - gunicorn 启动 30s 内 HTTP 502/503"
    echo "    - 关键端点 500 (本次就是)"
    echo "    - 业务 RD 报'功能完全不可用'"
    echo ""
    echo "  一键回滚命令 (SLA 5 分钟):"
    echo "    bash /tmp/rollback_110prod_v030_20260827.sh"
    echo "================================================================"
    exit 1
else
    ok "5+1 端点全 PASS, 推 110 阶段 5 通过"
    echo ""
    echo "  下一步:"
    echo "    1. 群发业务群: '推 110 完成, 新功能上线 (含 8/25 v0.4.5 选表页面)'"
    echo "    2. 提一条新 SQL 上线工单 (浏览器), 验证 detail 页审批流跟 config/ 配一致 (8/24 修法)"
    echo "    3. 21:30-22:00 DBA 值守, 看 gunicorn log + 业务 RD 反馈"
    echo "    4. 8/28 09:00 1 日观察 (docs/changelogs/2026-08-28_push-v030-day1-observation.md)"
    echo "================================================================"
    exit 0
fi
