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

Write-Host "=== DBA-bug-1 v2 push 110 prod (status_finish 也要触发) ===" -ForegroundColor Cyan

Write-Host "[1/5] scp push views.py"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_VIEWS" "root@172.20.2.110:$REMOTE/sql/views.py"

Write-Host "[2/5] chown + del pyc"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "chown archery:archery $REMOTE/sql/views.py; rm -f $REMOTE/sql/__pycache__/views.cpython-39.pyc"

Write-Host "[3/5] md5 verify"
$win = (Get-FileHash "$LOCAL_VIEWS" -Algorithm MD5).Hash
Write-Host "  Win: $win"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "md5sum $REMOTE/sql/views.py"

Write-Host "[4/5] reload gunicorn (kill -TERM workers, master 自动拉新)"
$reloadCmd = "ps -ef | grep gunicorn | grep -v 'bash -c' | awk '{print `$2}' | grep -v '`$`' | xargs -r kill -TERM 2>/dev/null; sleep 5; ps -ef | grep gunicorn | head -8"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 $reloadCmd

Write-Host "[5/5] done" -ForegroundColor Cyan
