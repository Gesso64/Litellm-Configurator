# Start the spike proxy on port 4099. Press Ctrl+C in this window to stop
# (it tails the log; Ctrl+C stops the tail AND kills the proxy).
#
# Why cmd.exe in the middle: PowerShell wraps every stderr line from a
# native command as an "error record", which (combined with -ErrorAction
# Stop) aborts the script before any log gets written. cmd.exe's '2>&1'
# happens at the OS level, so PowerShell only ever sees a clean process
# exit code.

if (-not $env:OPENROUTER_API_KEY) {
    Write-Host "ERROR: OPENROUTER_API_KEY env var not set in this terminal." -ForegroundColor Red
    Write-Host "Set it before starting the proxy:" -ForegroundColor Yellow
    Write-Host '  $env:OPENROUTER_API_KEY = "sk-or-v1-..."'
    exit 1
}

$repo    = (Resolve-Path "$PSScriptRoot\..").Path
$config  = "$PSScriptRoot\litellm-spike.yaml"
$logPath = "$PSScriptRoot\spike-proxy.log"
$litellm = "$repo\.venv\Scripts\litellm.exe"
if (-not (Test-Path $litellm)) { $litellm = "litellm" }

# Force UTF-8 for the child process — LiteLLM's startup banner has unicode
# chars that crash a cp1252 stdout on Windows.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8       = "1"

# Truncate the log so verdict.py only sees this session's traffic.
"" | Out-File -FilePath $logPath -Encoding utf8 -Force

Write-Host "Spike proxy starting on http://localhost:4099" -ForegroundColor Cyan
Write-Host "Log     -> $logPath"                            -ForegroundColor Cyan
Write-Host "Aliases -> agentA-main, agentB-main"            -ForegroundColor Cyan
Write-Host ""

# cmd.exe handles the redirection so PowerShell never sees the streams.
# Outer quotes for cmd; inner backtick-quotes for paths with spaces.
$cmdLine = "`"$litellm`" --config `"$config`" --port 4099 --detailed_debug > `"$logPath`" 2>&1"
$proc = Start-Process -NoNewWindow -PassThru `
    -FilePath "cmd.exe" -ArgumentList "/c", $cmdLine

Write-Host "Proxy PID: $($proc.Id) — waiting for it to come up..." -ForegroundColor DarkGray

# Inline health-poll up to 30s. Quiet on failure so we still tail logs.
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:4099/health/liveliness" `
                               -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}

if ($ready) {
    Write-Host '*** Proxy is READY on :4099. Run the agent scripts now. ***' -ForegroundColor Green
} else {
    Write-Host '!!! Proxy did NOT respond on :4099 within 30s. See log below. !!!' -ForegroundColor Red
}
Write-Host "Tailing log — Ctrl+C stops the tail AND the proxy." -ForegroundColor DarkGray
Write-Host ""

try {
    Get-Content -Path $logPath -Wait
} finally {
    if ($proc -and -not $proc.HasExited) {
        Write-Host ""
        Write-Host "Stopping proxy (PID $($proc.Id))..." -ForegroundColor Yellow
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}
