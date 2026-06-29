# Sourced from $PROFILE on every new PowerShell session.
# Generates one session id per shell and exports it as an HTTP header that
# Claude Code forwards to the LiteLLM proxy. Lets ~/.claude/litellm-session-log.jsonl
# attribute every request to the terminal it came from.

if (-not $env:CLAUDE_SESSION_ID) {
    $env:CLAUDE_SESSION_ID = ([guid]::NewGuid().ToString()).Substring(0, 8)
}

# Preserve any pre-existing custom headers — only append ours if absent.
if (-not $env:ANTHROPIC_CUSTOM_HEADERS) {
    $env:ANTHROPIC_CUSTOM_HEADERS = "x-session-id: $env:CLAUDE_SESSION_ID"
} elseif ($env:ANTHROPIC_CUSTOM_HEADERS -notmatch "x-session-id") {
    $env:ANTHROPIC_CUSTOM_HEADERS = "$env:ANTHROPIC_CUSTOM_HEADERS`nx-session-id: $env:CLAUDE_SESSION_ID"
}

function litellm-session { Write-Host "claude session_id = $env:CLAUDE_SESSION_ID" }
function litellm-tail {
    param([int]$N = 20)
    & python "F:\Programs\Github Repositories\Litellm-Configurator\tools\litellm_recent.py" `
        --session $env:CLAUDE_SESSION_ID --n $N
}
function litellm-follow {
    & python "F:\Programs\Github Repositories\Litellm-Configurator\tools\litellm_recent.py" `
        --session $env:CLAUDE_SESSION_ID --follow
}

Write-Host "[litellm] session_id=$env:CLAUDE_SESSION_ID  (litellm-tail / litellm-follow)" -ForegroundColor DarkGray
