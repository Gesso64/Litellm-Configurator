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
- **LiteLLM** installed globally (`pip install litellm`) — needed at runtime to launch the proxy
- **Claude Code** installed ([docs](https://docs.anthropic.com/en/docs/claude-code))

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/your-username/Litellm-Configurator.git
cd Litellm-Configurator

# 2. Install Python dependencies
pip install -r requirements.txt

# If you don't need the GUI, you can skip PySide6:
pip install litellm pyyaml requests

# 3. Set your OpenRouter API key
# Windows (PowerShell):
$env:OPENROUTER_API_KEY = "your_key_here"

# macOS / Linux:
export OPENROUTER_API_KEY="your_key_here"

# Or copy .env.example to .env and fill it in (for permanent setup)
```

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

### GUI (desktop app)

**Windows:**
```bat
run.bat gui
```

**Any platform:**
```bash
python start-litellm-gui.py
```

Requires `PySide6` (`pip install PySide6`).

## How it works

1. Fetches available models from the OpenRouter API using `OPENROUTER_API_KEY`
2. Presents a type-to-search picker for each role (Advisor, Agent, Subagent)
3. Optionally saves your selections as a named profile (`~/.claude/profiles/*.json`)
4. Generates a LiteLLM config at `~/.claude/litellm-select.yaml`
5. Optionally updates your `~/.claude/CLAUDE.md` routing table
6. Launches LiteLLM proxy on the chosen port

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
