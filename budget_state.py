from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path.home() / ".claude" / "litellm-budget.json"


@dataclass
class BudgetConfig:
    enabled: bool = False
    cap_usd: float = 5.0
    warn_threshold: float = 0.8       # 0..1
    auto_downgrade: bool = False      # opt-in; default OFF; NOT acted on by this module


@dataclass
class BudgetSignal:
    level: str               # "ok" | "warn" | "exceeded" | "disabled"
    pct_used: float          # 0..1 (may exceed 1 when over cap)
    remaining_usd: float     # max(0, cap - spent)
    message: str             # human-readable summary

    @property
    def warn_or_exceeded(self) -> bool:
        return self.level in ("warn", "exceeded")


def _coerce_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y", "t")
    return bool(value)


def load_config(path: Path = DEFAULT_PATH) -> BudgetConfig:
    """Load JSON; return BudgetConfig() defaults on missing file or any error.

    Coerce types defensively. Unknown keys are ignored. Missing keys take the
    dataclass default.
    """
    defaults = BudgetConfig()
    try:
        path = Path(path)
        if not path.exists():
            return defaults
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return defaults
        return BudgetConfig(
            enabled=_coerce_bool(data.get("enabled", defaults.enabled), defaults.enabled),
            cap_usd=_coerce_float(data.get("cap_usd", defaults.cap_usd), defaults.cap_usd),
            warn_threshold=_coerce_float(
                data.get("warn_threshold", defaults.warn_threshold),
                defaults.warn_threshold,
            ),
            auto_downgrade=_coerce_bool(
                data.get("auto_downgrade", defaults.auto_downgrade),
                defaults.auto_downgrade,
            ),
        )
    except Exception:
        return defaults


def save_config(cfg: BudgetConfig, path: Path = DEFAULT_PATH) -> None:
    """Write atomically: write to a sibling temp file then os.replace."""
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(asdict(cfg), indent=2, sort_keys=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise


def evaluate(cfg: BudgetConfig, spent_today_usd: float) -> BudgetSignal:
    """Pure: compute current signal."""
    spent = float(spent_today_usd)
    cap = float(cfg.cap_usd)

    if not cfg.enabled or cap <= 0:
        return BudgetSignal(
            level="disabled",
            pct_used=0.0,
            remaining_usd=0.0,
            message="Budget tracking disabled.",
        )

    pct_used = spent / cap
    remaining_usd = max(0.0, cap - spent)
    pct_int = int(round(pct_used * 100))

    if spent >= cap:
        message = (
            f"Over daily budget: ${spent:.2f} of ${cap:.2f}. "
            f"Consider switching to a cheaper tier."
        )
        level = "exceeded"
    elif spent >= cap * float(cfg.warn_threshold):
        message = (
            f"Approaching daily budget: ${spent:.2f} / ${cap:.2f} ({pct_int}%)."
        )
        level = "warn"
    else:
        message = f"Within budget: ${spent:.2f} / ${cap:.2f} ({pct_int}%)."
        level = "ok"

    return BudgetSignal(
        level=level,
        pct_used=pct_used,
        remaining_usd=remaining_usd,
        message=message,
    )
