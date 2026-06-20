# Litellm-Configurator

Interactive LiteLLM launcher — pick OpenRouter models for each role (advisor/agent/subagent) and launch the proxy.

## Files

- `start-litellm-select.py` — main script
- `run.bat` — Windows double-click launcher
- `start-litellm-select.sh` — bash launcher
- `litellm-flash.yaml`, `litellm-deepseek.yaml` — reference configs
- `cloud-analyze.py`, `cloud-doc.py` — companion scripts for analysis / doc edits

## Usage

```bash
python start-litellm-select.py
# or on macOS/Linux:
python3 start-litellm-select.py
```

| Flag | Description |
|------|-------------|
| `--port PORT` | Proxy port (default: 4001) |
| `--profile NAME` | Load saved profile, skip interactive |
| `--list-profiles` | List saved profiles |
| `--delete-profile NAME` | Delete a profile |
| `--no-launch` | Generate config only, don't start proxy |

## How it works

1. Fetches models from OpenRouter API (`OPENROUTER_API_KEY` env var)
2. Type-to-search picker for each role:
   - **Advisor** → alias `claude-opus-4-7`
   - **Agent** → alias `claude-sonnet-4-6`
   - **Subagent** → alias `claude-*` (catch-all)
3. Save selections as a named profile (`~/.claude/profiles/*.json`)
4. Generates `~/.claude/litellm-select.yaml`
5. Updates `~/.claude/CLAUDE.md` routing table
6. Launches LiteLLM on chosen port

## Dependencies

```bash
pip install requests pyyaml litellm

# GUI only:
pip install PySide6
```