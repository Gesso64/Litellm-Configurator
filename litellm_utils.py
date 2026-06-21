"""Shared utilities for start-litellm-gui.py and start-litellm-select.py."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".claude"
SCRIPTS_DIR = CONFIG_DIR / "scripts"
YAML_PATH = CONFIG_DIR / "litellm-select.yaml"
CLAUDE_MD_PATH = CONFIG_DIR / "CLAUDE.md"

ROLES = [
    ("advisor", "claude-opus-4-7", "Advisor"),
    ("agent", "claude-sonnet-4-6", "Agent"),
    ("subagent", "claude-*", "Subagent"),
]


def health_check(port: int, timeout: int = 10) -> bool:
    url = f"http://localhost:{port}/health/liveliness"
    for _ in range(timeout):
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def kill_process_on_port(port: int) -> bool:
    if platform.system() == "Windows":
        try:
            out = subprocess.check_output(
                f'netstat -ano | findstr "LISTENING" | findstr ":{port}"',
                shell=True, text=True, timeout=5,
            )
            for line in out.strip().splitlines():
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, timeout=5)
        except Exception:
            return False
    else:
        try:
            subprocess.run(["pkill", "-f", f"litellm.*--port {port}"],
                           capture_output=True, timeout=5)
        except Exception:
            return False
    time.sleep(2)
    return not health_check(port, timeout=3)


def find_litellm() -> str | None:
    """Return path to litellm executable, preferring project venv first."""
    script_dir = Path(sys.argv[0]).parent
    venv_dir = script_dir / ".venv"
    if venv_dir.exists():
        for candidate in [
            venv_dir / "Scripts" / "litellm.exe",
            venv_dir / "Scripts" / "litellm",
            venv_dir / "bin" / "litellm",
        ]:
            if candidate.exists():
                return str(candidate)
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["where", "litellm"], capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["which", "litellm"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def generate_yaml(models: dict, yaml_path: Path = YAML_PATH, vision_support: dict | None = None) -> None:
    import yaml
    model_list = []
    for role_key, alias, _ in ROLES:
        full_id = models.get(role_key, "")
        model_id = full_id.removeprefix("~")
        entry: dict = {
            "model_name": alias,
            "litellm_params": {
                "model": f"openrouter/{model_id}",
                "api_key": "os.environ/OPENROUTER_API_KEY",
            },
        }
        if vision_support is not None:
            entry["model_info"] = {"supports_vision": vision_support.get(role_key, False)}
        model_list.append(entry)
    config = {
        "model_list": model_list,
        "general_settings": {"master_key": "sk-local-fake"},
        "litellm_settings": {"drop_params": True},
        "router_settings": {
            "allowed_fails": 1000,
            "cooldown_time": 0,
        },
    }
    with open(yaml_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


_ROUTING_START = "<!-- litellm-routing-start -->"
_ROUTING_END = "<!-- litellm-routing-end -->"


def _build_routing_block(models: dict) -> str:
    advisor = models.get("advisor", "—").removeprefix("~")
    agent = models.get("agent", "—").removeprefix("~")
    subagent = models.get("subagent", "—").removeprefix("~")
    return "\n".join([
        _ROUTING_START,
        "| Alias | Maps to | Role |",
        "|-------|---------|------|",
        f"| claude-opus-4-7 | {advisor} | Advisor |",
        f"| claude-sonnet-4-6 | {agent} | Agent |",
        f"| claude-* | {subagent} | Subagent |",
        _ROUTING_END,
    ])


def update_claude_md(models: dict, port: int) -> bool | str:
    """Directly rewrite the LiteLLM routing table in CLAUDE.md — no LLM needed."""
    try:
        block = _build_routing_block(models)

        if not CLAUDE_MD_PATH.exists():
            CLAUDE_MD_PATH.write_text(
                f"## LiteLLM Proxy (OpenRouter)\n\n{block}\n", encoding="utf-8"
            )
            return True

        content = CLAUDE_MD_PATH.read_text(encoding="utf-8")

        # Case 1: markers already present — replace between them
        if _ROUTING_START in content and _ROUTING_END in content:
            new_content = re.sub(
                re.escape(_ROUTING_START) + r".*?" + re.escape(_ROUTING_END),
                block,
                content,
                flags=re.DOTALL,
            )
            CLAUDE_MD_PATH.write_text(new_content, encoding="utf-8")
            return True

        # Case 2: section header exists but no markers — insert block after header
        section_re = re.compile(
            r"(## LiteLLM Proxy \(OpenRouter\)[^\n]*\n)(\s*)(.*?)(?=\n## |\Z)",
            re.DOTALL,
        )
        if section_re.search(content):
            new_content = section_re.sub(
                lambda m: m.group(1) + "\n" + block + "\n",
                content,
            )
            CLAUDE_MD_PATH.write_text(new_content, encoding="utf-8")
            return True

        # Case 3: no section at all — append it
        sep = "\n\n" if not content.endswith("\n\n") else ""
        CLAUDE_MD_PATH.write_text(
            content + sep + f"## LiteLLM Proxy (OpenRouter)\n\n{block}\n",
            encoding="utf-8",
        )
        return True
    except Exception as exc:
        return str(exc)
