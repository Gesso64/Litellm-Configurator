# Litellm-Configurator

- **Path**: Clone to any local directory
- **Purpose**: Interactive LiteLLM model selector for OpenRouter
- **Main script**: `start-litellm-select.py`
- **Launchers**: `run.bat` (Windows), `start-litellm-select.sh` (bash)
- **Model aliases** (fixed): `claude-sonnet-4-6` (agent), `claude-opus-4-7` (advisor), `claude-*` (subagent catch-all)
- **Profiles stored**: `~/.claude/profiles/*.json`
- **Generated YAML**: `~/.claude/litellm-select.yaml`
- **CLI flags**: `--port`, `--profile`, `--list-profiles`, `--delete-profile`, `--no-launch`
- **Wrapper at**: `~/.claude/scripts/start-litellm-select.py` delegates to project copy