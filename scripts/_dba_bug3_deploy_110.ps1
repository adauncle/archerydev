# DBA-bug-3 push 110 prod
$ErrorActionPreference = 'Stop'
$PASSWORD = 'lAqfb8uEmQYsnGNQwIHtGPwukjCz6J'
$HOSTKEY = 'SHA256:DHkk6e+b9hkybykAzqxARzkng5AHfvmO8v5KY0XNsLU'
$REMOTE = '/dbdata/archery_v114_c9236a0'

$plink = 'F:\putty\plink.exe'
$pscp = 'F:\putty\pscp.exe'

pushd $PSScriptRoot\.. | Out-Null
$LROOT = (Get-Location).Path
popd | Out-Null

$LOCAL_COLUMN = "$LROOT\sql\extensions\ddl_gh_ost\services\column_diff.py"
$LOCAL_SQLSUBMIT = "$LROOT\sql\templates\sqlsubmit.html"

Write-Host "=== DBA-bug-3 push 110 prod (ADD/DROP INDEX 大表 alert) ===" -ForegroundColor Cyan

Write-Host "[1/5] backup"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "cp -v $REMOTE/sql/extensions/ddl_gh_ost/services/column_diff.py /tmp/column_diff.py.bak.20260911_1910; cp -v $REMOTE/sql/templates/sqlsubmit.html /tmp/sqlsubmit.html.bak.20260911_1910"

Write-Host "[2/5] scp push column_diff.py"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_COLUMN" "root@172.20.2.110:$REMOTE/sql/extensions/ddl_gh_ost/services/column_diff.py"

Write-Host "[3/5] scp push sqlsubmit.html"
& $pscp -pw $PASSWORD -hostkey $HOSTKEY "$LOCAL_SQLSUBMIT" "root@172.20.2.110:$REMOTE/sql/templates/sqlsubmit.html"

Write-Host "[4/5] chown + del pyc"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "chown archery:archery $REMOTE/sql/extensions/ddl_gh_ost/services/column_diff.py $REMOTE/sql/templates/sqlsubmit.html; rm -f $REMOTE/sql/extensions/ddl_gh_ost/services/__pycache__/column_diff.cpython-39.pyc"

Write-Host "[5/5] md5 verify + reload"
$winC = (Get-FileHash "$LOCAL_COLUMN" -Algorithm MD5).Hash
$winS = (Get-FileHash "$LOCAL_SQLSUBMIT" -Algorithm MD5).Hash
Write-Host "  column_diff.py Win: $winC"
Write-Host "  sqlsubmit Win:      $winS"
& $plink -ssh -pw $PASSWORD -hostkey $HOSTKEY root@172.20.2.110 "md5sum $REMOTE/sql/extensions/ddl_gh_ost/services/column_diff.py $REMOTE/sql/templates/sqlsubmit.html"

Write-Host "=== done ===" -ForegroundColor Cyan
