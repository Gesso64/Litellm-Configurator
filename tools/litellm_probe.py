"""Direct probe for the local LiteLLM proxy.

Usage:
  python tools/litellm_probe.py --list
  python tools/litellm_probe.py --ping claude-opus-4-8
  python tools/litellm_probe.py --all
  python tools/litellm_probe.py --ping claude-foo-bar --prompt "say hi"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORT = int(os.environ.get("LITELLM_PORT", "4001"))
DEFAULT_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-local-fake")
DEFAULT_PROMPT = "Reply with exactly: OK"


def _req(method: str, path: str, body: dict | None = None, port: int = DEFAULT_PORT, key: str = DEFAULT_KEY, timeout: int = 60):
    url = f"http://localhost:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
            return True, payload, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = {"error": str(e)}
        return False, payload, (time.perf_counter() - t0) * 1000
    except Exception as e:
        return False, {"error": str(e)}, (time.perf_counter() - t0) * 1000


def list_models(port: int, key: str) -> list[str]:
    ok, payload, _ = _req("GET", "/v1/models", port=port, key=key)
    if not ok:
        print(f"failed: {payload}", file=sys.stderr)
        return []
    return [m["id"] for m in payload.get("data", [])]


def ping(alias: str, prompt: str, port: int, key: str) -> dict:
    body = {
        "model": alias,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 16,
        "temperature": 0,
    }
    ok, payload, elapsed_ms = _req("POST", "/v1/chat/completions", body, port=port, key=key)
    result = {
        "alias_requested": alias,
        "ok": ok,
        "latency_ms": round(elapsed_ms, 1),
    }
    if ok:
        result["upstream_model"] = payload.get("model")
        usage = payload.get("usage", {}) or {}
        result["prompt_tokens"] = usage.get("prompt_tokens")
        result["completion_tokens"] = usage.get("completion_tokens")
        choices = payload.get("choices") or []
        if choices:
            msg = (choices[0].get("message") or {}).get("content") or ""
            result["reply"] = msg[:80]
    else:
        err = payload.get("error", payload)
        if isinstance(err, dict):
            result["error"] = err.get("message") or err.get("error") or str(err)[:200]
        else:
            result["error"] = str(err)[:200]
    return result


def fmt_row(r: dict) -> str:
    if r["ok"]:
        return (
            f"  OK   {r['alias_requested']:<24} -> {r.get('upstream_model','?'):<48} "
            f"{r['latency_ms']:>7.1f} ms  in={r.get('prompt_tokens')} out={r.get('completion_tokens')}  "
            f"reply={r.get('reply','')!r}"
        )
    return f"  FAIL {r['alias_requested']:<24} {r['latency_ms']:>7.1f} ms  err={r.get('error','?')}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--key", default=DEFAULT_KEY)
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--list", action="store_true", help="list aliases via /v1/models")
    p.add_argument("--ping", metavar="ALIAS", help="ping a single alias")
    p.add_argument("--all", action="store_true", help="ping every alias from /v1/models")
    p.add_argument("--wildcard-test", default="claude-haiku-test-fallthrough",
                   help="extra alias to send for wildcard fall-through verification")
    args = p.parse_args()

    if args.list or not (args.ping or args.all):
        aliases = list_models(args.port, args.key)
        print(f"proxy http://localhost:{args.port} aliases:")
        for a in aliases:
            print(f"  - {a}")
        if not args.ping and not args.all:
            return 0

    if args.ping:
        print(fmt_row(ping(args.ping, args.prompt, args.port, args.key)))

    if args.all:
        aliases = list_models(args.port, args.key)
        # Exclude bare wildcard pattern (proxy rejects literal "claude-*"); test fallthrough with a synthetic name
        targets = [a for a in aliases if a != "claude-*"]
        targets.append(args.wildcard_test)
        print(f"pinging {len(targets)} aliases:")
        for a in targets:
            print(fmt_row(ping(a, args.prompt, args.port, args.key)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
