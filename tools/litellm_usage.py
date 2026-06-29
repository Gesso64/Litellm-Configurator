"""Aggregate ~/.claude/litellm-session-log.jsonl by model.

Examples:
  python tools/litellm_usage.py                 # group by alias, all-time
  python tools/litellm_usage.py --by upstream   # group by upstream model
  python tools/litellm_usage.py --by both       # alias + upstream rollup
  python tools/litellm_usage.py --since 1h      # only the last hour
  python tools/litellm_usage.py --since 7d
  python tools/litellm_usage.py --session abc12345
"""
from __future__ import annotations
import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = Path.home() / ".claude" / "litellm-session-log.jsonl"


def parse_since(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s*([smhdw])", s.strip().lower())
    if not m:
        raise SystemExit(f"--since: expected like '30s' '5m' '2h' '7d', got {s!r}")
    n, unit = int(m.group(1)), m.group(2)
    delta = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[unit]
    return datetime.now(timezone.utc) - timedelta(**{delta: n})


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--by", choices=("alias", "upstream", "both"), default="alias",
                    help="group rows by alias (default), upstream model, or both")
    ap.add_argument("--since", help="only entries newer than this window (e.g. 30s, 5m, 2h, 7d)")
    ap.add_argument("--session", help="filter by session_id")
    ap.add_argument("--status", choices=("ok", "error", "all"), default="all")
    ap.add_argument("--log", default=str(LOG))
    args = ap.parse_args()

    cutoff = parse_since(args.since)
    log_path = Path(args.log)
    if not log_path.exists():
        raise SystemExit(f"no log at {log_path}")

    agg: dict[tuple, dict] = defaultdict(lambda: {
        "requests": 0, "errors": 0,
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        "cost_usd": 0.0, "latency_ms_sum": 0.0, "latency_count": 0,
    })

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        ts = parse_ts(e.get("ts"))
        if cutoff and ts and ts < cutoff:
            continue
        if args.session and e.get("session_id") != args.session:
            continue
        status = e.get("status")
        if args.status == "ok" and status != "ok":
            continue
        if args.status == "error" and status == "ok":
            continue

        alias = e.get("alias_requested") or "-"
        upstream = e.get("upstream_model") or "-"
        if args.by == "alias":
            key = (alias,)
        elif args.by == "upstream":
            key = (upstream,)
        else:
            key = (alias, upstream)

        row = agg[key]
        row["requests"] += 1
        if status != "ok":
            row["errors"] += 1
        for f in ("prompt_tokens", "completion_tokens", "total_tokens"):
            v = e.get(f) or 0
            row[f] += v if isinstance(v, (int, float)) else 0
        c = e.get("cost_usd") or 0
        if isinstance(c, (int, float)):
            row["cost_usd"] += float(c)
        lat = e.get("latency_ms")
        if isinstance(lat, (int, float)):
            row["latency_ms_sum"] += float(lat)
            row["latency_count"] += 1

    if not agg:
        print("(no matching entries)")
        return

    if args.by == "both":
        header_cols = ("alias", "upstream")
    elif args.by == "upstream":
        header_cols = ("upstream",)
    else:
        header_cols = ("alias",)

    # Sort by total_tokens desc
    rows = sorted(agg.items(), key=lambda kv: kv[1]["total_tokens"], reverse=True)

    key_w = max(
        sum(len(p) for p in k) + (3 if len(k) > 1 else 0)
        for k, _ in rows
    )
    key_w = max(key_w, sum(len(c) for c in header_cols) + (3 if len(header_cols) > 1 else 0))

    print(
        f"{' / '.join(header_cols):<{key_w}}  "
        f"{'reqs':>6}  {'err':>4}  {'in':>10}  {'out':>10}  {'total':>11}  {'cost$':>9}  {'avg_ms':>8}"
    )
    print("-" * (key_w + 70))
    totals = defaultdict(float)
    for k, r in rows:
        key_str = " / ".join(k)
        avg_lat = (r["latency_ms_sum"] / r["latency_count"]) if r["latency_count"] else 0
        print(
            f"{key_str:<{key_w}}  "
            f"{r['requests']:>6}  {r['errors']:>4}  "
            f"{r['prompt_tokens']:>10,}  {r['completion_tokens']:>10,}  {r['total_tokens']:>11,}  "
            f"{r['cost_usd']:>9.4f}  {avg_lat:>8.0f}"
        )
        totals["requests"] += r["requests"]
        totals["errors"] += r["errors"]
        totals["prompt_tokens"] += r["prompt_tokens"]
        totals["completion_tokens"] += r["completion_tokens"]
        totals["total_tokens"] += r["total_tokens"]
        totals["cost_usd"] += r["cost_usd"]
    print("-" * (key_w + 70))
    print(
        f"{'TOTAL':<{key_w}}  "
        f"{int(totals['requests']):>6}  {int(totals['errors']):>4}  "
        f"{int(totals['prompt_tokens']):>10,}  {int(totals['completion_tokens']):>10,}  "
        f"{int(totals['total_tokens']):>11,}  {totals['cost_usd']:>9.4f}"
    )


if __name__ == "__main__":
    main()
