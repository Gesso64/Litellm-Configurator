# Launch Claude Code with a unique x-session-id header so every request from
# this terminal is taggable in ~/.claude/litellm-session-log.jsonl.
#
# Usage:
#   .\tools\claude-debug.ps1                # generates a fresh session id
#   .\tools\claude-debug.ps1 -SessionId foo # use an explicit id
#   .\tools\claude-debug.ps1 -- <claude args>
[CmdletBinding()]
param(
    [string]$SessionId,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Rest
)

if (-not $SessionId) {
    $SessionId = ([guid]::NewGuid().ToString()).Substring(0, 8)
}

# ANTHROPIC_CUSTOM_HEADERS is read by Claude Code and forwarded to the proxy.
# Format: "Header-Name: value\nHeader-2: value2"
$env:ANTHROPIC_CUSTOM_HEADERS = "x-session-id: $SessionId"

Write-Host "[litellm-debug] session_id=$SessionId  (tail: python tools/litellm_recent.py --session $SessionId --follow)" -ForegroundColor Cyan

& claude @Rest
