"""Interactive LiteLLM launcher — pick OpenRouter models per role, launch the proxy."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SCRIPTS_DIR = Path.home() / ".claude" / "scripts"
CONFIG_DIR = Path.home() / ".claude"
PROFILES_DIR = CONFIG_DIR / "profiles"
YAML_PATH = CONFIG_DIR / "litellm-select.yaml"
CLAUDE_MD_PATH = CONFIG_DIR / "CLAUDE.md"

# (role_key, model_name_alias, display_label)
ROLES = [
    ("advisor", "claude-opus-4-7", "Advisor"),
    ("agent", "claude-sonnet-4-6", "Agent"),
    ("subagent", "claude-*", "Subagent"),
]

DEFAULT_MODELS = {
    "advisor": "anthropic/claude-opus-latest",
    "agent": "deepseek/deepseek-v4-flash",
    "subagent": "deepseek/deepseek-v4-flash",
}


def die(msg: str, code: int = 1) -> None:
    print(f"[start-litellm-select] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def fetch_models() -> list[dict]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        die("OPENROUTER_API_KEY not set. Set it as a system env var and restart.")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        die(f"Failed to fetch models from OpenRouter: {exc}")
    models = data.get("data", [])
    if not models:
        die("OpenRouter returned empty model list.")
    models.sort(key=lambda m: m.get("id", ""))
    return models


def fmt_model(m: dict) -> str:
    mid = m.get("id", "?")
    name = m.get("name", "")
    ctx = m.get("context_length", 0)
    pricing = m.get("pricing", {})
    p_in = float(pricing.get("prompt", 0) or 0)
    p_out = float(pricing.get("completion", 0) or 0)
    ctx_k = f"{ctx // 1000}K" if ctx else "?"
    return f"{mid:<55s} {name:<40s} {ctx_k:>6s}  ${p_in:.8f}/in  ${p_out:.8f}/out"


def interactive_select(models: list[dict], role: str, alias: str, default: str | None = None) -> str:
    print(f"\n--- {role} (alias: {alias}) ---")
    if role == "Subagent" and default:
        print(f"  (Enter for same as Agent: {default})")

    page_size = 20
    query = ""
    filtered = list(models)
    page = 0

    while True:
        q = query.lower()
        if q:
            filtered = [
                m for m in models
                if q in m.get("id", "").lower() or q in m.get("name", "").lower()
            ]
        else:
            filtered = list(models)

        if not filtered:
            print("  No models match. Try a different search.")
            query = input("  Search models: ").strip()
            page = 0
            continue

        total = len(filtered)
        start = page * page_size
        end = min(start + page_size, total)
        chunk = filtered[start:end]
        n_pages = (total + page_size - 1) // page_size

        print(f"  {total} models  (showing {start + 1}-{end} of {total})")
        for i, m in enumerate(chunk, start=start + 1):
            print(f"  [{i:4d}] {fmt_model(m)}")
        print(f"  Page {page + 1}/{n_pages}")

        if end < total:
            print("  (Enter for next page)", end="")

        prompt = "  Type number (or more text to filter)"
        if not q:
            prompt = "  Search models (or Enter for all)"

        inp = input(f"{prompt}: ").strip()

        if not inp:
            if not q and end < total:
                page += 1
                continue
            elif default:
                return default
            continue

        if inp == "q":
            print("  (can't skip — enter a model number)")
            continue

        if inp.isdigit():
            idx = int(inp) - 1
            if 0 <= idx < total:
                selected = filtered[idx]
                mid = selected.get("id", "")
                print(f"  => {role}: {mid}")
                return mid

        # Treat as new search filter
        query = inp
        page = 0


def save_profile(name: str, port: int, models: dict) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"{name}.json"
    if path.exists():
        resp = input(f"  Profile '{name}' already exists. Overwrite? [y/N] ").strip().lower()
        if resp != "y":
            print("  Skipped.")
            return path
    data = {
        "name": name,
        "port": port,
        "models": models,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved to {path}")
    return path


def load_profile(name: str) -> dict:
    path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        available = list_profiles()
        names = ", ".join(a[0] for a in available) if available else "(none)"
        die(f"Profile '{name}' not found. Available: {names}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_profiles() -> list[tuple[str, dict]]:
    if not PROFILES_DIR.exists():
        return []
    result = []
    for f in sorted(PROFILES_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        result.append((data.get("name", f.stem), data.get("models", {})))
    return result


def generate_yaml(models: dict) -> None:
    import yaml
    model_list = []
    for role_key, alias, _ in ROLES:
        model_list.append({
            "model_name": alias,
            "litellm_params": {
                "model": f"openrouter/{models[role_key]}",
                "api_key": "os.environ/OPENROUTER_API_KEY",
            },
        })
    config = {
        "model_list": model_list,
        "general_settings": {"master_key": "sk-local-fake"},
        "litellm_settings": {"drop_params": True},
    }
    with open(YAML_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"  Wrote {YAML_PATH}")


def update_claude_md(models: dict, port: int) -> None:
    lines = [
        "Update the model routing table in CLAUDE.md:",
        f"- claude-sonnet-4-6 -> {models['agent']} (Agent)",
        f"- claude-opus-4-7 -> {models['advisor']} (Advisor)",
        f"- claude-* -> {models['subagent']} (Subagent)",
        "",
        "Specifically update the table rows under '## LiteLLM Proxy (OpenRouter)'.",
        "Keep all other sections unchanged.",
    ]
    instruction = "\n".join(lines)
    cloud_doc = SCRIPTS_DIR / "cloud-doc.py"
    if not cloud_doc.exists():
        print("  [warn] cloud-doc.py not found; update CLAUDE.md routing table manually.")
        print(f"  New routing: {models}")
        return
    try:
        subprocess.run(
            [sys.executable, str(cloud_doc), str(CLAUDE_MD_PATH), instruction,
             "--model", "claude-opus-4-7", "--port", str(port)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        print("  Updated CLAUDE.md routing table.")
    except subprocess.CalledProcessError as exc:
        print(f"  [warn] cloud-doc.py failed to update CLAUDE.md.")
        print(f"  stderr: {exc.stderr[:300]}" if exc.stderr else "")
        print(f"  New routing — update manually in CLAUDE.md:")
        for role_key, alias, label in ROLES:
            print(f"    {alias} -> {models[role_key]}")


def health_check(port: int, timeout: int = 15) -> bool:
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


def launch_litellm(config_path: Path, port: int) -> None:
    if health_check(port, timeout=1):
        print(f"  Port {port} already has a LiteLLM running.")
        inp = input("  Kill it and restart? [y/N] ").strip().lower()
        if inp == "y":
            if kill_process_on_port(port):
                print("  Killed existing process.")
            else:
                print("  Could not kill existing process. Use --port to pick a different port.")
                return
        else:
            print("  Keeping existing. Use --no-launch to just generate config.")
            return

    print(f"  Starting LiteLLM on port {port}...")
    log_path = Path(tempfile.gettempdir()) / "litellm-select.log"
    pid_path = Path(tempfile.gettempdir()) / "litellm-select.pid"

    try:
        proc = subprocess.Popen(
            ["litellm", "--config", str(config_path), "--port", str(port)],
            env={**os.environ, "PYTHONIOENCODING": "utf-8",
                 "PYTHONUTF8": "1", "SSLKEYLOGFILE": ""},
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except FileNotFoundError:
        die("litellm not found. Install with: pip install litellm")

    pid_path.write_text(str(proc.pid))

    if health_check(port):
        print(f"  LiteLLM is running on port {port} (PID {proc.pid}).")
    else:
        last = log_path.read_text().splitlines()[-10:] if log_path.exists() else []
        print(f"  LiteLLM did not start within 15s. Last {len(last)} log lines:", file=sys.stderr)
        for line in last:
            print(f"    {line}", file=sys.stderr)
        print(f"  Full log: {log_path}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive LiteLLM model selector for OpenRouter")
    parser.add_argument("--port", type=int, default=4001, help="Proxy port (default: 4001)")
    parser.add_argument("--profile", help="Load a saved profile instead of interactive mode")
    parser.add_argument("--list-profiles", action="store_true", help="List saved profiles and exit")
    parser.add_argument("--delete-profile", help="Delete a saved profile and exit")
    parser.add_argument("--no-launch", action="store_true", help="Generate config but don't start LiteLLM")
    args = parser.parse_args()

    if args.list_profiles:
        profiles = list_profiles()
        if not profiles:
            print("No profiles saved.")
        else:
            print("Saved profiles:")
            for name, models in profiles:
                print(f"  {name}")
                for rk, _, lb in ROLES:
                    print(f"    {lb}: {models.get(rk, '?')}")
        return

    if args.delete_profile:
        path = PROFILES_DIR / f"{args.delete_profile}.json"
        if path.exists():
            path.unlink()
            print(f"Deleted profile '{args.delete_profile}'.")
        else:
            available = [p.stem for p in PROFILES_DIR.glob("*.json")] if PROFILES_DIR.exists() else []
            die(f"Profile '{args.delete_profile}' not found. Available: {', '.join(available) or '(none)'}")
        return

    port = args.port

    if args.profile:
        profile = load_profile(args.profile)
        models = profile.get("models", {})
        port = profile.get("port", port)
        print(f"Loaded profile '{args.profile}':")
        for rk, _, lb in ROLES:
            print(f"  {lb}: {models.get(rk, '?')}")
        print(f"  Port: {port}")
    else:
        print("=== LiteLLM Model Selector ===")
        print("Fetching models from OpenRouter...", end=" ")
        sys.stdout.flush()
        all_models = fetch_models()
        print(f"{len(all_models)} models available.")

        models = {}
        for role_key, alias, label in ROLES:
            default_for_subagent = models.get("agent") if role_key == "subagent" else None
            mid = interactive_select(all_models, label, alias, default=default_for_subagent)
            models[role_key] = mid

        resp = input("\nSave as named profile? [y/N] ").strip().lower()
        if resp == "y":
            name = input("Profile name: ").strip()
            if name:
                save_profile(name, port, models)

    print("\nGenerating LiteLLM config...")
    generate_yaml(models)

    if not args.no_launch:
        launch_litellm(YAML_PATH, port)
        update_claude_md(models, port)
    else:
        print("  --no-launch: config written, proxy not started.")
        print(f"  Start manually: litellm --config {YAML_PATH} --port {port}")


if __name__ == "__main__":
    main()