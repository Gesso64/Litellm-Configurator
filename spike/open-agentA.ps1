# Opens a new PowerShell window posing as Agent A. Claude Code in this
# window will (we expect) send 'model: agentA-main' to the spike proxy.
$banner = @'
==========================================================================
  Phase 0 spike — Agent A
  ANTHROPIC_MODEL          = agentA-main
  ANTHROPIC_SMALL_FAST_MODEL = agentA-main
  Proxy                    = http://localhost:4099
==========================================================================
Type a one-liner like:  claude "say hi"
Then look in spike-proxy.log for 'agentA-main' in the request body.
'@

$cmd = @"
`$env:ANTHROPIC_BASE_URL = 'http://localhost:4099'
`$env:ANTHROPIC_API_KEY  = 'sk-local-fake'
`$env:ANTHROPIC_MODEL    = 'agentA-main'
`$env:ANTHROPIC_SMALL_FAST_MODEL = 'agentA-main'
Write-Host @'
$banner
'@ -ForegroundColor Cyan
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
