"""Pure utility module for OpenRouter pricing and LiteLLM session spend computation.

No PySide6, no litellm, no network. Stdlib only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Pricing:
    input_per_1m: Optional[float]
    output_per_1m: Optional[float]
    chip_label: str


@dataclass
class RoleSpend:
    advisor: float = 0.0
    agent: float = 0.0
    subagent: float = 0.0
    other: float = 0.0

    @property
    def total(self) -> float:
        return self.advisor + self.agent + self.subagent + self.other


@dataclass
class Spend:
    today_usd: float = 0.0
    session_usd: float = 0.0
    by_role_today: RoleSpend = field(default_factory=RoleSpend)
    request_count_today: int = 0
    last_request_utc: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_price_string(value) -> Optional[float]:
    """Parse a per-token price string into per-1M float. None if missing/zero/bad."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f <= 0.0:
        return None
    return f * 1_000_000.0


def _format_price(p: Optional[float]) -> str:
    if p is None:
        return "—"
    if p < 0.0001:
        return f"${p:.6f}"
    if p < 0.10:
        return f"${p:.4f}"
    return f"${p:.2f}"


def _parse_ts(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp, supporting Z suffix."""
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    # Handle Z suffix robustly across Python versions
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _alias_to_role(alias: str) -> str:
    if alias in ("claude-opus-4-7", "claude-opus-4-8"):
        return "advisor"
    if alias == "claude-sonnet-4-6":
        return "agent"
    if isinstance(alias, str) and alias.startswith("claude-"):
        return "subagent"
    return "other"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_pricing(model: dict) -> Pricing:
    """Pull input/output prices from an OpenRouter model dict and build chip label."""
    pricing = (model or {}).get("pricing") or {}
    input_per_1m = _parse_price_string(pricing.get("prompt"))
    output_per_1m = _parse_price_string(pricing.get("completion"))

    if input_per_1m is None and output_per_1m is None:
        chip = "—"
    else:
        chip = f"{_format_price(input_per_1m)} / {_format_price(output_per_1m)} per 1M"

    return Pricing(
        input_per_1m=input_per_1m,
        output_per_1m=output_per_1m,
        chip_label=chip,
    )


def compute_spend(
    log_path: Path,
    price_map: dict,
    session_gap_minutes: int = 30,
) -> Spend:
    """Walk JSONL session log and compute today + session spend."""
    log_path = Path(log_path)
    if not log_path.exists():
        return Spend()

    # Each entry: (datetime, cost_usd, role, alias)
    entries: list[tuple[datetime, float, str, str]] = []

    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("status") != "ok":
                    continue
                upstream = rec.get("upstream_model")
                if upstream not in price_map:
                    continue
                pricing = price_map[upstream]
                if pricing.input_per_1m is None or pricing.output_per_1m is None:
                    continue
                try:
                    pt = int(rec.get("prompt_tokens") or 0)
                    ct = int(rec.get("completion_tokens") or 0)
                except (TypeError, ValueError):
                    continue
                ts = _parse_ts(rec.get("timestamp_utc", ""))
                if ts is None:
                    continue
                cost = (
                    pt * pricing.input_per_1m + ct * pricing.output_per_1m
                ) / 1_000_000.0
                alias = rec.get("alias_requested", "") or ""
                role = _alias_to_role(alias)
                entries.append((ts, cost, role, alias))
    except OSError:
        return Spend()

    if not entries:
        return Spend()

    entries.sort(key=lambda e: e[0])

    # Today filter (UTC midnight)
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    today_entries = [e for e in entries if e[0] >= midnight]
    today_usd = sum(e[1] for e in today_entries)

    role_spend = RoleSpend()
    for _, cost, role, _alias in today_entries:
        if role == "advisor":
            role_spend.advisor += cost
        elif role == "agent":
            role_spend.agent += cost
        elif role == "subagent":
            role_spend.subagent += cost
        else:
            role_spend.other += cost

    # Session: find LAST gap > session_gap_minutes; session = everything after that gap.
    gap_seconds = session_gap_minutes * 60
    last_gap_idx = -1
    for i in range(1, len(entries)):
        delta = (entries[i][0] - entries[i - 1][0]).total_seconds()
        if delta > gap_seconds:
            last_gap_idx = i
    if last_gap_idx == -1:
        session_usd = sum(e[1] for e in entries)
    else:
        session_usd = sum(e[1] for e in entries[last_gap_idx:])

    last_ts = entries[-1][0]
    last_request_utc = last_ts.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )

    return Spend(
        today_usd=today_usd,
        session_usd=session_usd,
        by_role_today=role_spend,
        request_count_today=len(today_entries),
        last_request_utc=last_request_utc,
    )


def estimate_preset_cost(
    role_models: dict,
    price_map_by_model_id: dict,
    mix: Optional[dict] = None,
) -> str:
    """Weighted-blend daily-style cost estimate for a preset, in $X.XX/1M in format."""
    if mix is None:
        mix = {"advisor": 0.1, "agent": 0.3, "subagent": 0.6}

    total = 0.0
    for role, weight in mix.items():
        model_id = role_models.get(role)
        if not model_id:
            return "—"
        lookup = model_id.lstrip("~")
        pricing = price_map_by_model_id.get(lookup)
        if pricing is None or pricing.input_per_1m is None:
            return "—"
        total += weight * pricing.input_per_1m

    return f"${total:.2f}/1M in"
