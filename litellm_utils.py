"""Shared utilities for start-litellm-gui.py and start-litellm-select.py."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".claude"
SCRIPTS_DIR = CONFIG_DIR / "scripts"
YAML_PATH = CONFIG_DIR / "litellm-select.yaml"
CLAUDE_MD_PATH = CONFIG_DIR / "CLAUDE.md"
VISION_ROUTER_JSON = CONFIG_DIR / "vision-router.json"
VISION_ROUTER_PY = CONFIG_DIR / "vision_router.py"
SPEND_DB_PATH = CONFIG_DIR / "litellm-spend.db"

# Alias used for the dedicated vision-capable fallback deployment.
VISION_FALLBACK_ALIAS = "vision-fallback"
# Used when "Auto" is selected but none of the configured roles support vision.
DEFAULT_VISION_FALLBACK_MODEL = "google/gemini-2.5-flash-lite"

ROLES = [
    ("advisor", "claude-opus-4-7", "Advisor"),
    ("agent", "claude-sonnet-4-6", "Agent"),
    ("subagent", "claude-*", "Subagent"),
]

# Additional aliases that should share a role's mapping. The default Claude Code
# model id changes over time (e.g. claude-opus-4-8 replaced 4-7); we publish
# the role's underlying upstream model under all of these aliases so requests
# are routed correctly regardless of which default the client picks.
ROLE_EXTRA_ALIASES: dict[str, list[str]] = {
    "advisor": ["claude-opus-4-8"],
}


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


def resolve_auto_vision_fallback(models: dict, vision_support: dict | None) -> str:
    """Pick a vision-capable model for the 'Auto' fallback choice.

    Prefers reusing whichever configured role already supports images (advisor →
    agent → subagent); if none do, falls back to a cheap built-in vision model.
    Returns a bare OpenRouter model id (preserving the ``~`` prefix for latest-track aliases).
    """
    vision_support = vision_support or {}
    for role_key, _, _ in ROLES:
        if vision_support.get(role_key):
            mid = models.get(role_key, "")
            if mid:
                return mid
    return DEFAULT_VISION_FALLBACK_MODEL


def write_vision_router_config(
    vision_support: dict | None,
    fallback_alias: str | None,
    path: Path = VISION_ROUTER_JSON,
) -> None:
    """Write the sidecar the vision_router hook reads. ``fallback_alias`` is None
    when the feature is off (images then pass through and may error)."""
    vision_map = {}
    for role_key, alias, _ in ROLES:
        vision_map[alias] = bool((vision_support or {}).get(role_key, False))
    data = {
        "enabled": bool(fallback_alias),
        "vision_map": vision_map,
        "fallback_alias": fallback_alias,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def generate_yaml(
    models: dict,
    yaml_path: Path = YAML_PATH,
    vision_support: dict | None = None,
    vision_fallback: str | None = None,
) -> None:
    """Generate the LiteLLM config.

    ``vision_fallback`` is a bare OpenRouter model id (already resolved from the
    GUI's Auto/Off/Choose control) to route image requests to when the target
    model lacks vision; ``None`` disables the feature.
    """
    import yaml
    model_list = []
    for role_key, alias, _ in ROLES:
        full_id = models.get(role_key, "")
        model_id = full_id
        aliases = [alias] + ROLE_EXTRA_ALIASES.get(role_key, [])
        for a in aliases:
            entry: dict = {
                "model_name": a,
                "litellm_params": {
                    "model": f"openrouter/{model_id}",
                    "api_key": "os.environ/OPENROUTER_API_KEY",
                    "metadata": {"lc_alias": a},
                },
            }
            if vision_support is not None:
                entry["model_info"] = {"supports_vision": vision_support.get(role_key, False)}
            model_list.append(entry)

    litellm_settings: dict = {"drop_params": True}
    callbacks: list[str] = ["litellm_session_logger.instance"]
    fallback_alias: str | None = None
    if vision_fallback:
        fb_id = vision_fallback
        model_list.append({
            "model_name": VISION_FALLBACK_ALIAS,
            "litellm_params": {
                "model": f"openrouter/{fb_id}",
                "api_key": "os.environ/OPENROUTER_API_KEY",
            },
            "model_info": {"supports_vision": True},
        })
        callbacks.append("vision_router.instance")
        fallback_alias = VISION_FALLBACK_ALIAS
    litellm_settings["callbacks"] = callbacks

    config = {
        "model_list": model_list,
        "general_settings": {
            "master_key": "sk-local-fake",
        },
        "litellm_settings": litellm_settings,
        "router_settings": {
            "allowed_fails": 1000,
            "cooldown_time": 0,
        },
    }
    with open(yaml_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Write the sidecar next to the YAML so the deployed hook finds it.
    write_vision_router_config(
        vision_support, fallback_alias, path=yaml_path.parent / VISION_ROUTER_JSON.name
    )


def deploy_vision_router(dest_dir: Path = CONFIG_DIR) -> bool:
    """Copy vision_router.py next to the config so the proxy can import it.
    Returns True on success."""
    src = Path(__file__).resolve().parent / "vision_router.py"
    try:
        if src.exists():
            shutil.copyfile(src, dest_dir / "vision_router.py")
            return True
    except Exception:
        pass
    return False


def deploy_session_logger(dest_dir: Path = CONFIG_DIR) -> bool:
    """Copy litellm_session_logger.py next to the config so the proxy can import it."""
    src = Path(__file__).resolve().parent / "litellm_session_logger.py"
    try:
        if src.exists():
            shutil.copyfile(src, dest_dir / "litellm_session_logger.py")
            return True
    except Exception:
        pass
    return False


# Markers must match claude_md_renderer.py exactly — they're a contract.
_ROUTING_START = "<!-- litellm-routing-start -->"
_ROUTING_END = "<!-- litellm-routing-end -->"


def _build_routing_block(
    models: dict,
    preset_name: str | None = None,
    pricing_by_role: dict | None = None,
    budget=None,
) -> str:
    """Delegate to the richer renderer in claude_md_renderer.py."""
    from claude_md_renderer import render_routing_block
    return render_routing_block(models, preset_name, pricing_by_role, budget)


def update_claude_md(
    models: dict,
    port: int,
    preset_name: str | None = None,
    pricing_by_role: dict | None = None,
    budget=None,
) -> bool | str:
    """Directly rewrite the LiteLLM routing table in CLAUDE.md — no LLM needed.

    Optional kwargs flow through to the renderer for the richer block:
    preset_name, pricing_by_role={"advisor": "$X / $Y per 1M", ...},
    budget=claude_md_renderer.BudgetView(...).
    """
    try:
        block = _build_routing_block(models, preset_name, pricing_by_role, budget)

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
