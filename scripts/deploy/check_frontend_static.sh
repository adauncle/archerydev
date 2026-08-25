#!/bin/bash
# check_frontend_static.sh — 验证前端 dist 目录完整性 (8/25 新增)
#
# 用途: 134 dev / 110 prod 推代码后, 验证 static/dist 目录完整
#       8/25 教训: 5 端点验证只测 HTTP 200 状态, 没看 HTML 里 CSS/JS 引用是否 404
#                  134 dev 业务 RD 一直在用残废的 /sqlworkflow/ 没人反馈
#
# 检查项:
#   1. 9 个关键文件存在 (static/dist + common/static/dist, 4 js + 2 css + 3 .gz)
#   2. HTTP curl 验证 4 个 URL 返 200 (不跳登录, 没 MIME 错)
#
# 跑法 (在 110 prod 内部, 134 dev 也行):
#   bash /tmp/check_frontend_static.sh
#
# 环境变量 (可选, 都有默认值):
#   PROD_PATH   默认 /opt/archery/prod (134 dev) 或 /dbdata/archery_v114_c9236a0 (110 prod)
#   ARCHERY_URL 默认 http://127.0.0.1:9003 (134 dev) 或 http://127.0.0.1:9123 (110 prod)
#                演练时传 134 dev 演练: ARCHERY_URL=http://172.20.2.134:9003
#
# 期望输出:
#   [SUMMARY] dist 9/9 文件 + 4/4 URL OK
#   全部 OK = 推代码后 dist 完整, 业务 RD 不会用残废页面
#
# 作者: mavis @ 2026-08-25
# 关联: 8/25 教训 (134 dev static dist 缺失)

set -u  # 不用 -e, 全部检查都跑, 不一个失败就 exit

# 默认值 (auto-detect 134 dev vs 110 prod)
if [[ -d "/dbdata/archery_v114_c9236a0" ]]; then
    PROD_PATH="${PROD_PATH:-/dbdata/archery_v114_c9236a0}"
    ARCHERY_URL="${ARCHERY_URL:-http://127.0.0.1:9123}"
else
    PROD_PATH="${PROD_PATH:-/opt/archery/prod}"
    ARCHERY_URL="${ARCHERY_URL:-http://127.0.0.1:9003}"
fi

# 颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok() { echo -e "${GREEN}[$(date +%H:%M:%S)] OK${NC} $*"; }
err() { echo -e "${RED}[$(date +%H:%M:%S)] ERR${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] WARN${NC} $*"; }

# 状态计数
FILE_OK=0
FILE_FAIL=0
FILE_MISSING=""

URL_OK=0
URL_FAIL=0
URL_FAIL_LIST=""

echo "================================================================"
echo "check_frontend_static.sh — 验证前端 dist 目录完整性 (8/25 新增)"
echo "  时间: $(date)"
echo "  PROD_PATH: ${PROD_PATH}"
echo "  ARCHERY_URL: ${ARCHERY_URL}"
echo "================================================================"

# === 前置检查 ===
echo ""
echo "=== 前置检查 ==="
if [[ ! -d "${PROD_PATH}" ]]; then
    err "代码目录不存在: ${PROD_PATH}"
    echo "  排查: ls -la ${PROD_PATH%/*}"
    exit 1
fi
ok "代码目录存在: ${PROD_PATH}"

# 端口可达
if ! curl -sI --max-time 5 "${ARCHERY_URL}/" >/dev/null 2>&1; then
    err "无法连 ${ARCHERY_URL}, 排查端口 / gunicorn 进程"
    exit 1
fi
ok "端口可达: ${ARCHERY_URL}"

# === 关键文件检查 (9 个) ===
echo ""
echo "=== 关键文件检查 (9 个) ==="

FILES=(
    "static/dist/css/login.css"
    "static/dist/css/login.css.gz"
    "static/dist/js/formatter.js"
    "static/dist/js/formatter.js.gz"
    "static/dist/js/utils.js"
    "static/dist/js/utils.js.gz"
    "static/dist/js/marked.min.js"
    "static/dist/js/marked.min.js.gz"
    "common/static/dist/css/login.css"
    "common/static/dist/js/formatter.js"
    "common/static/dist/js/marked.min.js"
    "common/static/dist/js/utils.js"
)

for f in "${FILES[@]}"; do
    full="${PROD_PATH}/${f}"
    if [[ -f "${full}" ]]; then
        size=$(stat -c '%s' "${full}" 2>/dev/null || stat -f '%z' "${full}" 2>/dev/null || echo "?")
        ok "文件存在 (${size} bytes): ${f}"
        FILE_OK=$((FILE_OK + 1))
    else
        err "文件缺失: ${f}"
        FILE_FAIL=$((FILE_FAIL + 1))
        FILE_MISSING="${FILE_MISSING} ${f}"
    fi
done

# === HTTP 200 验证 (4 个 URL) ===
echo ""
echo "=== HTTP 200 验证 (4 个 URL, 期望 200 不跳登录) ==="

URLS=(
    "/static/dist/css/login.css"
    "/static/dist/js/formatter.js"
    "/static/dist/js/utils.js"
    "/static/dist/js/marked.min.js"
)

for u in "${URLS[@]}"; do
    http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${ARCHERY_URL}${u}" 2>&1)
    if [[ "${http_code}" == "200" ]]; then
        ok "HTTP 200: ${u}"
        URL_OK=$((URL_OK + 1))
    else
        err "HTTP ${http_code}: ${u} (期望 200)"
        URL_FAIL=$((URL_FAIL + 1))
        URL_FAIL_LIST="${URL_FAIL_LIST} ${u}(${http_code})"
    fi
done

# === MIME type 验证 (防 HTML 当 CSS/JS 错) ===
echo ""
echo "=== MIME type 验证 (防 HTML 当 CSS/JS 错) ==="
# Django 默认 serve JS MIME 是 text/javascript (RFC 9239), 浏览器都接受
# 期望: css=text/css, js=text/javascript 或 application/javascript
MIME_CHECKS=(
    "css:text/css:/static/dist/css/login.css"
    "js:text/javascript:/static/dist/js/formatter.js"
    "js:text/javascript:/static/dist/js/utils.js"
)

for check in "${MIME_CHECKS[@]}"; do
    IFS=':' read -r kind expected_mime path <<< "${check}"
    actual_mime=$(curl -sI --max-time 5 "${ARCHERY_URL}${path}" 2>&1 | grep -i 'content-type:' | head -1 | tr -d '\r\n' | sed 's/.*[Cc]ontent-[Tt]ype:[[:space:]]*//')
    # 检查是否在可接受 MIME 列表中
    if echo "${actual_mime}" | grep -qi "${expected_mime}"; then
        ok "MIME 正确 (${actual_mime}): ${path}"
    elif echo "${actual_mime}" | grep -qi 'application/javascript'; then
        ok "MIME 可接受 (${actual_mime}, application/javascript 是 text/javascript 等价): ${path}"
    elif echo "${actual_mime}" | grep -qi 'text/html'; then
        err "MIME 错 (${actual_mime} = text/html, 期望 ${expected_mime}): ${path}"
        warn "  根因: Django 找不到 static 文件, 返 302 跳登录, 浏览器把 HTML 当 CSS/JS"
        warn "  修法: 跑 npm run build 生成 dist, 或从 110 prod scp dist 文件"
        URL_FAIL=$((URL_FAIL + 1))
    else
        warn "MIME 异常 (${actual_mime}, 期望 ${expected_mime}): ${path}"
    fi
done

# === 总结 ===
echo ""
echo "================================================================"
echo "[SUMMARY]"
echo "  文件: ${FILE_OK}/${#FILES[@]} 存在"
echo "  URL:  ${URL_OK}/${#URLS[@]} HTTP 200"
echo ""

if [[ ${FILE_FAIL} -gt 0 || ${URL_FAIL} -gt 0 ]]; then
    err "前端 static 验证 FAIL"
    if [[ -n "${FILE_MISSING}" ]]; then
        echo ""
        echo "  缺失文件:"
        for f in ${FILE_MISSING}; do
            echo "    - ${f}"
        done
        echo ""
        echo "  修法:"
        echo "    方案 A (推荐): 从 110 prod scp dist 文件"
        echo "      ssh root@172.20.2.110"
        echo "      cd /dbdata/archery_v114_c9236a0"
        echo "      tar -czf /tmp/110prod_dist.tar.gz static/dist common/static/dist"
        echo "      # 134 dev 端:"
        echo "      cd /opt/archery/prod"
        echo "      tar -xzf /tmp/110prod_dist.tar.gz"
        echo "      chown -R archery:archery static/dist common/static/dist"
        echo ""
        echo "    方案 B: 134 dev 上 npm run build (需装 node + npm)"
        echo "      cd /opt/archery/prod"
        echo "      # 前端 source 在 sql/static/src/ 或 common/static/src/"
        echo "      # 具体 build 命令参考 Archery 上游 docs"
    fi
    if [[ -n "${URL_FAIL_LIST}" ]]; then
        echo ""
        echo "  失败 URL:"
        for u in ${URL_FAIL_LIST}; do
            echo "    - ${u}"
        done
    fi
    echo "================================================================"
    exit 1
else
    ok "前端 static 验证全 PASS, 业务 RD 不会用残废页面"
    echo ""
    echo "  8/25 教训: 演练必查前端 static (不只 HTTP 200, 还要 CSS/JS 引用不 404)"
    echo "================================================================"
    exit 0
fi
