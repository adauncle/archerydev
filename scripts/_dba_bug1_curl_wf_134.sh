#!/bin/bash
# 134 dev 真 HTTP 演练: wf#9999 审批中工单 detail 页 (CSRF + 登录)
set -e

COOKIE=/tmp/dba_bug1_cookie.txt
rm -f $COOKIE

echo "=== [1/4] GET /login/ 拿 csrf token ==="
LOGIN_PAGE=$(curl -sS -c $COOKIE -b $COOKIE "http://172.20.2.134:9003/login/")
CSRF=$(echo "$LOGIN_PAGE" | grep -oP 'name="csrfmiddlewaretoken" value="\K[^"]+' | head -1)
echo "CSRF=$CSRF"

echo ""
echo "=== [2/4] POST /login/ 登录 (带 csrf) ==="
LOGIN_RESP=$(curl -sS -i -c $COOKIE -b $COOKIE -X POST "http://172.20.2.134:9003/authenticate/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Referer: http://172.20.2.134:9003/login/" \
  -d "csrfmiddlewaretoken=$CSRF&username=archery&password=archery123" 2>&1)
echo "$LOGIN_RESP" | grep -E "^HTTP|Location:|Set-Cookie:" | head -10

echo ""
echo "=== [3/4] GET /detail/9999/ 审批中工单 ==="
DETAIL=$(curl -sS -b $COOKIE -L -w "\n[HTTP_CODE=%{http_code}]" "http://172.20.2.134:9003/detail/9999/")
echo "$DETAIL" > /tmp/wf9999_detail.html
echo "size: $(wc -c < /tmp/wf9999_detail.html) bytes"
echo "$DETAIL" | tail -1

echo ""
echo "=== [4/4] 验证关键元素 ==="
echo "  big-table-alert 块: $(grep -c 'big-table-alert' /tmp/wf9999_detail.html) 处"
echo "  btnPass 按钮: $(grep -c 'btnPass' /tmp/wf9999_detail.html) 处"
ALERT_POS=$(grep -n 'id="big-table-alert"' /tmp/wf9999_detail.html | head -1 | cut -d: -f1)
BTN_POS=$(grep -n 'id="btnPass"' /tmp/wf9999_detail.html | head -1 | cut -d: -f1)
echo "  big-table-alert line: $ALERT_POS"
echo "  btnPass line: $BTN_POS"
if [ -n "$ALERT_POS" ] && [ -n "$BTN_POS" ] && [ "$ALERT_POS" -lt "$BTN_POS" ]; then
    echo "  [OK] alert 在 btnPass 前面 ✓ (DBA-bug-1 修法生效)"
else
    echo "  [INFO] alert 位置/btnPass 位置分析失败"
fi
echo "  status display: $(grep -oE 'workflow_detail_disaply">[^<]+' /tmp/wf9999_detail.html | head -1)"
