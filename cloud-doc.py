"""Edit a markdown or YAML file through LiteLLM proxy (DeepSeek Flash via OpenRouter)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a doc/config file through LiteLLM")
    parser.add_argument("file", type=Path)
    parser.add_argument("instruction")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--port", default="4001")
    args = parser.parse_args()

    content = args.file.read_text(encoding="utf-8")
    prompt = (
        f"{content}\n\n"
        f"Task: {args.instruction}\n\n"
        "Return only the complete updated file content. No commentary, no markdown fences, no preamble."
    )
    payload = json.dumps({
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://localhost:{args.port}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer sk-local-fake"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
            result = body["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"[cloud-doc] LiteLLM unavailable ({exc}). Edit the file manually.", file=sys.stderr)
        raise SystemExit(1) from exc

    args.file.write_text(result, encoding="utf-8")
    print(f"[cloud-doc] updated {args.file} via {args.model}")


if __name__ == "__main__":
    main()