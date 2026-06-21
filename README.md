# Litellm-Configurator

Interactive LiteLLM launcher — pick [OpenRouter](https://openrouter.ai) models for each Claude Code role (advisor/agent/subagent) and launch the proxy. Provides both a terminal CLI and a desktop GUI.

## What it does

This tool lets you route [Claude Code](https://docs.anthropic.com/en/docs/claude-code) model calls through OpenRouter via a local [LiteLLM](https://github.com/BerriAI/litellm) proxy. Instead of editing YAML by hand, you get an interactive picker to choose which OpenRouter model handles each role:

| Claude Code role | Alias | Typical use |
|-----------------|-------|-------------|
| Advisor | `claude-opus-4-7` | High-quality reasoning |
| Agent | `claude-sonnet-4-6` | Main task execution |
| Subagent | `claude-*` (catch-all) | Parallel sub-tasks |

## Prerequisites

- **Python 3.10+**
- An **OpenRouter API key** — [get one here](https://openrouter.ai/keys)
- **Claude Code** installed ([docs](https://docs.anthropic.com/en/docs/claude-code))

## Installation

All dependencies install into a **project-local virtual environment** (`.venv/`). No global pip installs needed.

```bash
# 1. Clone the repo
git clone https://github.com/your-username/Litellm-Configurator.git
cd Litellm-Configurator

# 2. Create the virtual environment and install dependencies
python -m venv .venv

# Windows:
.venv\Scripts\pip install -r requirements.txt

# macOS / Linux:
.venv/bin/pip install -r requirements.txt

# If you don't need the GUI, you can skip PySide6:
#   pip install litellm pyyaml requests

# 3. Set your OpenRouter API key
# Windows (PowerShell):
$env:OPENROUTER_API_KEY = "your_key_here"

# macOS / Linux:
export OPENROUTER_API_KEY="your_key_here"

# Or copy .env.example to .env and fill it in (for permanent setup)
```

> **Note:** The `.bat` launchers (`run.bat` / `run-gui.bat`) automate the venv setup — they auto-create `.venv` and install deps on first run if missing. The Python scripts also prefer the local `.venv`'s `litellm` binary when launching the proxy.

## Usage

### CLI (terminal)

**Windows:**
```bat
run.bat
```

**macOS / Linux:**
```bash
./start-litellm-select.sh
```

**Any platform:**
```bash
python start-litellm-select.py
```

#### CLI flags

| Flag | Description |
|------|-------------|
| `--port PORT` | Proxy port (default: 4001) |
| `--profile NAME` | Load a saved profile, skip interactive picker |
| `--list-profiles` | List all saved profiles |
| `--delete-profile NAME` | Delete a saved profile |
| `--no-launch` | Generate config only, don't start the proxy |

After launching, a persistent banner shows the active model routing:

```
╔══════════════════════════════════════════════════════════════╗
║               LiteLLM Proxy — Active Models                ║
╠══════════════════════════════════════════════════════════════╣
║  Port: 4001                                                    ║
║  Advisor     claude-opus-4-7      →  anthropic/claude-opus-latest ║
║  Agent       claude-sonnet-4-6    →  deepseek/deepseek-v4-flash  ║
║  Subagent    claude-*             →  deepseek/deepseek-v4-flash  ║
╠══════════════════════════════════════════════════════════════╣
║  Proxy running in background. Use claude with:             ║
║    ANTHROPIC_BASE_URL=http://localhost:4001                  ║
║    ANTHROPIC_API_KEY=sk-local-fake                          ║
╚══════════════════════════════════════════════════════════════╝

Press Enter to dismiss this banner and return to shell...
```

The banner stays on screen until you press Enter, so you can note the active models before continuing.

### GUI (desktop app)

**Windows:**
```bat
run.bat gui
```

**Any platform:**
```bash
python start-litellm-gui.py
```

Requires `PySide6` (included in `requirements.txt` — installs into `.venv`).

## How it works

1. The launcher auto-creates a project `.venv` (or uses an existing one) and ensures deps are installed
2. Fetches available models from the OpenRouter API using `OPENROUTER_API_KEY`
3. Presents a type-to-search picker for each role (Advisor, Agent, Subagent)
4. Optionally saves your selections as a named profile (`~/.claude/profiles/*.json`)
5. Generates a LiteLLM config at `~/.claude/litellm-select.yaml`
6. Optionally updates your `~/.claude/CLAUDE.md` routing table
7. Launches LiteLLM proxy on the chosen port
8. Shows a persistent model banner (dismiss on Enter) so you can verify routing before using Claude Code

## Files

| File | Description |
|------|-------------|
| `start-litellm-select.py` | CLI interactive model selector |
| `start-litellm-gui.py` | PySide6 desktop GUI |
| `run.bat` | Windows double-click launcher |
| `start-litellm-select.sh` | Bash launcher (macOS / Linux) |
| `litellm-flash.yaml` | Reference config (DeepSeek Flash) |
| `litellm-deepseek.yaml` | Reference config (DeepSeek Pro) |
| `cloud-analyze.py` | Send text/files through the running proxy |
| `cloud-doc.py` | Edit markdown/YAML files through the proxy |

## Companion scripts

`cloud-analyze.py` and `cloud-doc.py` send requests to the running LiteLLM proxy. They require the proxy to be running first.

```bash
python cloud-analyze.py "Summarize this" --file myfile.txt
python cloud-doc.py myfile.md "Update the introduction section"
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | ✅ Yes | Your OpenRouter API key |

See `.env.example` for a template.

## License

MIT — see [LICENSE](LICENSE)
