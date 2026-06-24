# Same idea as Agent A, but with the agentB-main alias.
$banner = @'
==========================================================================
  Phase 0 spike — Agent B
  ANTHROPIC_MODEL          = agentB-main
  ANTHROPIC_SMALL_FAST_MODEL = agentB-main
  Proxy                    = http://localhost:4099
==========================================================================
Type a one-liner like:  claude "say hi"
Then look in spike-proxy.log for 'agentB-main' in the request body.
'@

$cmd = @"
`$env:ANTHROPIC_BASE_URL = 'http://localhost:4099'
`$env:ANTHROPIC_API_KEY  = 'sk-local-fake'
`$env:ANTHROPIC_MODEL    = 'agentB-main'
`$env:ANTHROPIC_SMALL_FAST_MODEL = 'agentB-main'
Write-Host @'
$banner
'@ -ForegroundColor Magenta
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
