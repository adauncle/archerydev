# DBA-bug-2 push 110 prod
# 修法: views.py regex 改支持反引号 schema (跟 column_diff.py 一致) + sqlsubmit.html 主页面 banner
$ErrorActionPreference = 'Stop'
$PASSWORD = 'lAqfb8uEmQYsnGNQwIHtGPwukjCz6J'
$HOSTKEY = 'SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU'
$REMOTE = '/dbdata/archery_v114_c9236a0'

$plink = 'F:\putty\plink.exe'
$pscp = 'F:\putty\pscp.exe'

pushd $PSScriptRoot\.. | Out-Null
$LROOT = (Get-Location).Path
popd | Out-Null

$LOCAL_VIEWS = "$LROOT\sql\views.py"
$LOCAL_SQLSUBMIT = "$LROOT\sql\templates\sqlsubmit.html"

Write-Host "=== DBA-bug-2 push 110 prod (regex + sqlsubmit banner) ===" -ForegroundColor Cyan

Write-Host "[1/6] backup"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "cp -v $REMOTE/sql/views.py /tmp/views.py.bak.20260911_1835 && cp -v $REMOTE/sql/templates/sqlsubmit.html /tmp/sqlsubmit.html.bak.20260911_1835"

Write-Host "[2/6] scp push views.py"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_VIEWS" "root@172.20.2.110:$REMOTE/sql/views.py"

Write-Host "[3/6] scp push sqlsubmit.html"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_SQLSUBMIT" "root@172.20.2.110:$REMOTE/sql/templates/sqlsubmit.html"

Write-Host "[4/6] chown + del pyc"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "chown archery:archery $REMOTE/sql/views.py $REMOTE/sql/templates/sqlsubmit.html; rm -f $REMOTE/sql/__pycache__/views.cpython-39.pyc"

Write-Host "[5/6] md5 verify"
$winV = (Get-FileHash "$LOCAL_VIEWS" -Algorithm MD5).Hash
$winS = (Get-FileHash "$LOCAL_SQLSUBMIT" -Algorithm MD5).Hash
Write-Host "  views.py Win:     $winV"
Write-Host "  sqlsubmit Win:    $winS"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "md5sum $REMOTE/sql/views.py $REMOTE/sql/templates/sqlsubmit.html"

Write-Host "[6/6] reload gunicorn (kill -TERM workers)"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "WORKERS=\$(ps -ef | grep gunicorn | grep -v 'bash -c' | awk '{print \$2}' | head -10); echo killing: \$WORKERS; kill -TERM \$WORKERS 2>/dev/null; sleep 5; ps -ef | grep gunicorn | head -8"

Write-Host "=== DBA-bug-2 push done ===" -ForegroundColor Cyan
