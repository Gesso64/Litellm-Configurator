"""Analyze text or a file through LiteLLM proxy (DeepSeek Flash via OpenRouter)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Analyze a prompt or file through LiteLLM")
    parser.add_argument("input")
    parser.add_argument("prompt", nargs="?")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--port", default="4001")
    args = parser.parse_args()

    input_path = Path(args.input)
    if args.prompt is None:
        prompt = args.input
        content = ""
    elif input_path.is_file():
        prompt = args.prompt
        content = input_path.read_text(encoding="utf-8")
    else:
        print("Usage: cloud-analyze.py \"prompt\"", file=sys.stderr)
        print("       cloud-analyze.py <file> \"prompt about file\"", file=sys.stderr)
        raise SystemExit(1)

    full_prompt = f"{content}\n\n{prompt}".strip() if content else prompt
    payload = json.dumps({
        "model": args.model,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://localhost:{args.port}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer sk-local-fake"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
            print(body["choices"][0]["message"]["content"].strip())
    except Exception as exc:
        print(f"[cloud-analyze] LiteLLM unavailable ({exc})", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()