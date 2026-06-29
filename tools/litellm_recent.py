"""Inspect the session JSONL log written by litellm_session_logger.

Usage:
  python tools/litellm_recent.py                   # last 20 entries
  python tools/litellm_recent.py --n 50
  python tools/litellm_recent.py --alias claude-opus-4-8
  python tools/litellm_recent.py --since 5m        # 5m, 1h, 24h
  python tools/litellm_recent.py --errors
  python tools/litellm_recent.py --session <id>
  python tools/litellm_recent.py --summary         # counts by alias / upstream
  python tools/litellm_recent.py --follow          # tail -f
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG_PATH = Path(os.environ.get(
    "LITELLM_SESSION_LOG",
    str(Path.home() / ".claude" / "litellm-session-log.jsonl"),
))


def _parse_since(spec: str) -> datetime:
    m = re.fullmatch(r"(\d+)\s*([smhd])", spec.strip())
    if not m:
        raise ValueError(f"--since must look like 30s/5m/2h/1d, got {spec!r}")
    n, unit = int(m.group(1)), m.group(2)
    delta = {"s": timedelta(seconds=n), "m": timedelta(minutes=n),
             "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    return datetime.now(timezone.utc) - delta


def _iter_entries(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _passes(entry: dict, args) -> bool:
    if args.alias and entry.get("alias_requested") != args.alias:
        return False
    if args.session and entry.get("session_id") != args.session:
        return False
    if args.errors and entry.get("status") != "error":
        return False
    if args.since:
        ts = entry.get("ts")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            if dt < _parse_since(args.since):
                return False
        except Exception:
            return False
    return True


def _fmt(entry: dict) -> str:
    ts = entry.get("ts", "?")[:23]
    status = entry.get("status", "?")
    alias = entry.get("alias_requested") or "?"
    upstream = entry.get("upstream_model") or "?"
    pt = entry.get("prompt_tokens")
    ct = entry.get("completion_tokens")
    lat = entry.get("latency_ms")
    sess = entry.get("session_id") or "-"
    err = entry.get("error")
    base = f"{ts}  {status:<5} {alias:<30} -> {upstream:<42}  in={pt} out={ct} lat={lat}ms sess={sess}"
    if err:
        base += f"  ERR={err[:120]}"
    return base


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--alias")
    p.add_argument("--session")
    p.add_argument("--since", help="e.g. 30s 5m 2h 1d")
    p.add_argument("--errors", action="store_true")
    p.add_argument("--summary", action="store_true")
    p.add_argument("--follow", action="store_true", help="tail -f mode")
    p.add_argument("--path", default=str(LOG_PATH))
    args = p.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"log not found: {path}", file=sys.stderr)
        return 1

    if args.follow:
        with path.open("r", encoding="utf-8") as f:
            f.seek(0, 2)
            try:
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if _passes(entry, args):
                        print(_fmt(entry))
            except KeyboardInterrupt:
                return 0

    entries = [e for e in _iter_entries(path) if _passes(e, args)]

    if args.summary:
        by_alias = Counter(e.get("alias_requested") for e in entries)
        by_upstream = Counter(e.get("upstream_model") for e in entries)
        by_status = Counter(e.get("status") for e in entries)
        print(f"total: {len(entries)}  status: {dict(by_status)}")
        print("by alias:")
        for k, v in by_alias.most_common():
            print(f"  {v:>5}  {k}")
        print("by upstream:")
        for k, v in by_upstream.most_common():
            print(f"  {v:>5}  {k}")
        return 0

    for e in entries[-args.n:]:
        print(_fmt(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
