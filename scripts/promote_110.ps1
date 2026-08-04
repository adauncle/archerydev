# ============================================================
# promote_110.ps1 —— Windows 触发器，把 promote_110.sh 喂给 110 跑
#
# 用法（双击或在 PowerShell 跑）：
#   .\promote_110.ps1 v0.2.0              # 默认 dry-run
#   .\promote_110.ps1 v0.2.0 --no-dry-run # 真推
#   .\promote_110.ps1 2a393a4 --no-dry-run --skip-migrate
#
# 流程：
#   1. 读 scripts\promote_110.sh
#   2. 通过 ssh 把内容喂给 110 上的 bash
#   3. 110 上执行主逻辑
# ============================================================

$ErrorActionPreference = 'Stop'

param(
    [Parameter(Mandatory = $true)][string]$GitRef,
    [switch]$NoDryRun,
    [switch]$SkipMigrate
)

# 路径
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = Split-Path -Parent $ScriptDir
$ShPath      = Join-Path $ScriptDir "promote_110.sh"
$ProdHost    = "root@172.20.2.110"
$ProdUserHome = "/root"

# 颜色
function Log([string]$Msg)   { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Msg" -ForegroundColor Cyan }
function Warn([string]$Msg)  { Write-Host "[WARN] $Msg" -ForegroundColor Yellow }
function Err([string]$Msg)   { Write-Host "[ERR] $Msg" -ForegroundColor Red; exit 1 }
function Ok([string]$Msg)    { Write-Host "[OK] $Msg" -ForegroundColor Green }

# 0. 预检
Log "promote_110.ps1 启动"
Log "Git ref: $GitRef"
Log "Mode: $(if ($NoDryRun) { 'REAL（实际执行）' } else { 'DRY-RUN' })"
Log "Skip-mig: $(if ($SkipMigrate) { 'YES' } else { 'NO' })"
Log ""

# 1. 检查 promote_110.sh 存在
if (-not (Test-Path $ShPath)) {
    Err "找不到 $ShPath"
}

# 2. 检查 dev 仓库工作区干净
Log "[0.1] 检查 dev 仓库工作区"
$gitStatus = & git -C $RepoRoot status --porcelain 2>&1
if ($LASTEXITCODE -ne 0) {
    Err "git status 失败: $gitStatus"
}
if ($gitStatus) {
    Err "dev 仓库有未提交变更: $gitStatus"
}
Ok "[0.1] dev 仓库干净"

# 3. 解析 git ref
Log "[0.2] 解析 git ref: $GitRef"
$resolved = & git -C $RepoRoot rev-parse $GitRef 2>&1
if ($LASTEXITCODE -ne 0) {
    Err "git ref 解析失败: $resolved"
}
$shortCommit = $resolved.Substring(0, 7)
Ok "[0.2] $GitRef = $shortCommit"

# 4. 检查 110 可达
Log "[0.3] 检查 110 PROD 可达"
try {
    $null = & ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 $ProdHost "echo connected" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Err "110 PROD 不可达"
    }
    Ok "[0.3] 110 PROD 可达"
} catch {
    Err "ssh 失败: $_"
}

# 5. 构造传给 110 的参数
$remoteArgs = @($GitRef)
if ($NoDryRun) { $remoteArgs += "--no-dry-run" }
if ($SkipMigrate) { $remoteArgs += "--skip-migrate" }
$remoteCmd = "bash -s -- $($remoteArgs -join ' ')"
Log "[0.4] 远程命令: ssh $ProdHost '$remoteCmd'"

# 6. 确认
if (-not $NoDryRun) {
    Log ""
    Log "============================================================"
    Log "DRY-RUN 模式：只打印不执行"
    Log "实际推 110 需要加 --no-dry-run 参数"
    Log "============================================================"
}

if ($NoDryRun) {
    Log ""
    Log "实际推 110 PROD，确认要继续？"
    $confirm = Read-Host "输入 yes 继续（其他取消）"
    if ($confirm -ne "yes") {
        Log "取消"
        exit 0
    }
}

# 7. 通过 ssh 把 promote_110.sh 内容喂给 110 跑
Log "[0.5] 推 promote_110.sh 到 110 执行"
Log "       $ShPath | ssh $ProdHost '$remoteCmd'"

# 用 Get-Content 读 .sh，按行传给 ssh（避免长字符串 quoting 问题）
# 但 ssh 接收 stdin 要用 `bash -s`，sh 文件内容要按行 echo
# 最稳的方式: 写到本地临时文件，scp 到 110，再 ssh 触发
# 但 scp 中文路径有问题
# 次稳: cat $ShPath | ssh ... "bash -s -- <args>" —— 这才是真正 "stdin 喂" 的方式

Log "[0.6] 启动 ssh 远程执行（会显示 110 端日志）"
Log ""

# 用 Get-Content 读 .sh 通过管道传给 ssh
# 注意: PowerShell 默认 UTF-16 LE，bash 端要 UTF-8
$content = Get-Content -Path $ShPath -Raw -Encoding UTF8
$bytes = [System.Text.Encoding]::UTF8.GetBytes($content)

# 用 Process 通过 stdin 传
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "ssh"
$psi.Arguments = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $ProdHost `"$remoteCmd`""
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.StandardInputEncoding = [System.Text.Encoding]::UTF8
$psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
$psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

$proc = [System.Diagnostics.Process]::Start($psi)

# 异步读 stdout/stderr
$outTask = $proc.StandardOutput.ReadToEndAsync()
$errTask = $proc.StandardError.ReadToEndAsync()

# 写 stdin
$stdin = $proc.StandardInput
$stdin.BaseStream.Write($bytes, 0, $bytes.Length)
$stdin.BaseStream.Flush()
$stdin.Close()

# 等待完成
$proc.WaitForExit()
$outText = $outTask.Result
$errText = $errTask.Result

# 输出
if ($outText) { Write-Host $outText }
if ($errText) { Write-Host $errText -ForegroundColor Yellow }

if ($proc.ExitCode -eq 0) {
    Log ""
    Ok "promote_110 完成（exit 0）"
} else {
    Err "promote_110 失败（exit $($proc.ExitCode)）"
}
