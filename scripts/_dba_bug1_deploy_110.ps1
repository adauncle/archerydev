# DBA-bug-1 push 110 prod
# 推 3 个文件: views.py / detail.html / changelog
# 110 prod 路径: /dbdata/archery_v114_c9236a0
# 110 prod 密码: lAqfb8uEmQYsnGNQwIHtGPwukjCz6J (D39 实战新发现)
# 110 prod plink hostkey: SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU (D39 实战新发现)
$ErrorActionPreference = 'Stop'
$PASSWORD = 'lAqfb8uEmQYsnGNQwIHtGPwukjCz6J'
$HOSTKEY = 'SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU'
$REMOTE = '/dbdata/archery_v114_c9236a0'

$plink = 'F:\putty\plink.exe'
$pscp = 'F:\putty\pscp.exe'

pushd $PSScriptRoot\.. | Out-Null
$LROOT = (Get-Location).Path
popd | Out-Null
Write-Host "Project root: $LROOT"

$LOCAL_VIEWS = "$LROOT\sql\views.py"
$LOCAL_DETAIL = "$LROOT\sql\templates\detail.html"
$LOCAL_CHANGELOG = "$LROOT\docs\changelogs\2026-09-11_dba-bug-1-big-table-alert-drop-index-and-review-visibility.md"

Write-Host "=== DBA-bug-1 push 110 prod ===" -ForegroundColor Cyan

Write-Host ""
Write-Host "[1/8] backup 110 prod old files"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "cp -v $REMOTE/sql/views.py /tmp/views.py.bak.20260911_1640 && cp -v $REMOTE/sql/templates/detail.html /tmp/detail.html.bak.20260911_1640"

Write-Host ""
Write-Host "[2/8] scp push views.py"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_VIEWS" "root@172.20.2.110:$REMOTE/sql/views.py"

Write-Host ""
Write-Host "[3/8] scp push detail.html"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_DETAIL" "root@172.20.2.110:$REMOTE/sql/templates/detail.html"

Write-Host ""
Write-Host "[4/8] scp push changelog"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_CHANGELOG" "root@172.20.2.110:$REMOTE/docs/changelogs/2026-09-11_dba-bug-1-big-table-alert-drop-index-and-review-visibility.md"

Write-Host ""
Write-Host "[5/8] chown"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "chown -v archery:archery $REMOTE/sql/views.py $REMOTE/sql/templates/detail.html $REMOTE/docs/changelogs/2026-09-11_dba-bug-1-big-table-alert-drop-index-and-review-visibility.md"

Write-Host ""
Write-Host "[6/8] del __pycache__"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "rm -fv $REMOTE/sql/__pycache__/views.cpython-39.pyc 2>&1; rm -fv $REMOTE/sql/__pycache__/views.cpython-311.pyc 2>&1"

Write-Host ""
Write-Host "[7/8] md5 compare"
Write-Host "--- Windows local md5 ---"
Write-Host "  views.py:    $((Get-FileHash "$LOCAL_VIEWS" -Algorithm MD5).Hash)"
Write-Host "  detail.html: $((Get-FileHash "$LOCAL_DETAIL" -Algorithm MD5).Hash)"
Write-Host "  changelog:   $((Get-FileHash "$LOCAL_CHANGELOG" -Algorithm MD5).Hash)"
Write-Host "--- 110 prod md5 ---"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "md5sum $REMOTE/sql/views.py $REMOTE/sql/templates/detail.html $REMOTE/docs/changelogs/2026-09-11_dba-bug-1-big-table-alert-drop-index-and-review-visibility.md"

Write-Host ""
Write-Host "[8/8] reload gunicorn"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "ps -ef | grep gunicorn | head -3; pkill -HUP -f 'gunicorn archery.wsgi'; sleep 3; ps -ef | grep gunicorn | head -5"

Write-Host ""
Write-Host "=== DBA-bug-1 push done ===" -ForegroundColor Cyan
