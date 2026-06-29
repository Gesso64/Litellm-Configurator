"""Tests for cost_utils."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure repo root on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cost_utils import (  # noqa: E402
    Pricing,
    Spend,
    RoleSpend,
    compute_spend,
    estimate_preset_cost,
    extract_pricing,
)


# ---------------------------------------------------------------------------
# extract_pricing
# ---------------------------------------------------------------------------


def test_extract_pricing_happy_path():
    model = {"pricing": {"prompt": "0.000003", "completion": "0.000015"}}
    p = extract_pricing(model)
    assert p.input_per_1m == pytest.approx(3.0)
    assert p.output_per_1m == pytest.approx(15.0)
    assert p.chip_label == "$3.00 / $15.00 per 1M"


def test_extract_pricing_missing():
    p = extract_pricing({"pricing": {}})
    assert p.input_per_1m is None
    assert p.output_per_1m is None
    assert p.chip_label == "—"


def test_extract_pricing_zero_treated_as_missing():
    p = extract_pricing({"pricing": {"prompt": "0", "completion": "0.0"}})
    assert p.input_per_1m is None
    assert p.output_per_1m is None
    assert p.chip_label == "—"


def test_extract_pricing_partial():
    p = extract_pricing({"pricing": {"prompt": "0.000003", "completion": "0"}})
    assert p.input_per_1m == pytest.approx(3.0)
    assert p.output_per_1m is None
    assert p.chip_label == "$3.00 / — per 1M"


def test_extract_pricing_low_price_precision():
    # 0.00000005 USD/token = $0.05 per 1M -> 4-decimal format
    p = extract_pricing({"pricing": {"prompt": "0.00000005", "completion": "0.00000005"}})
    assert p.input_per_1m == pytest.approx(0.05)
    assert p.chip_label == "$0.0500 / $0.0500 per 1M"


# ---------------------------------------------------------------------------
# compute_spend helpers
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_log(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _default_price_map():
    return {
        "deepseek/deepseek-v4-flash": Pricing(1.0, 2.0, "$1.00 / $2.00 per 1M"),
        "anthropic/claude-sonnet-latest": Pricing(3.0, 15.0, "$3.00 / $15.00 per 1M"),
        "z-ai/glm-5.2": Pricing(2.0, 4.0, "$2.00 / $4.00 per 1M"),
    }


# ---------------------------------------------------------------------------
# compute_spend
# ---------------------------------------------------------------------------


def test_compute_spend_no_file(tmp_path):
    spend = compute_spend(tmp_path / "nope.jsonl", _default_price_map())
    assert spend.today_usd == 0.0
    assert spend.session_usd == 0.0
    assert spend.request_count_today == 0
    assert spend.last_request_utc is None
    assert spend.by_role_today.total == 0.0


def test_compute_spend_skips_non_ok(tmp_path):
    log = tmp_path / "log.jsonl"
    now = datetime.now(timezone.utc)
    _write_log(
        log,
        [
            {
                "timestamp_utc": _iso(now),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "error",
            },
            {
                "timestamp_utc": _iso(now),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "ok",
            },
        ],
    )
    spend = compute_spend(log, _default_price_map())
    assert spend.request_count_today == 1
    assert spend.today_usd == pytest.approx(1.0)


def test_compute_spend_today_filtering(tmp_path):
    log = tmp_path / "log.jsonl"
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1, hours=2)
    _write_log(
        log,
        [
            {
                "timestamp_utc": _iso(yesterday),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "ok",
            },
            {
                "timestamp_utc": _iso(now),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 500_000,
                "completion_tokens": 0,
                "status": "ok",
            },
        ],
    )
    spend = compute_spend(log, _default_price_map())
    assert spend.request_count_today == 1
    assert spend.today_usd == pytest.approx(0.5)


def test_compute_spend_role_attribution(tmp_path):
    log = tmp_path / "log.jsonl"
    now = datetime.now(timezone.utc)
    pmap = _default_price_map()
    records = []
    for offset, alias in enumerate(
        [
            "claude-opus-4-7",   # advisor
            "claude-sonnet-4-6", # agent
            "claude-*",          # subagent
            "random-alias",      # other
        ]
    ):
        records.append(
            {
                "timestamp_utc": _iso(now - timedelta(minutes=offset)),
                "alias_requested": alias,
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "ok",
            }
        )
    _write_log(log, records)
    spend = compute_spend(log, pmap)
    assert spend.by_role_today.advisor == pytest.approx(1.0)
    assert spend.by_role_today.agent == pytest.approx(1.0)
    assert spend.by_role_today.subagent == pytest.approx(1.0)
    assert spend.by_role_today.other == pytest.approx(1.0)
    assert spend.by_role_today.total == pytest.approx(4.0)


def test_compute_spend_session_gap(tmp_path):
    log = tmp_path / "log.jsonl"
    now = datetime.now(timezone.utc)
    # Entry 1: now - 120 min
    # Entry 2: now - 90 min  (close to #1, 30-min gap edge)
    # Entry 3: now            (60-min gap from #2 -> > 30 minutes)
    _write_log(
        log,
        [
            {
                "timestamp_utc": _iso(now - timedelta(minutes=120)),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "ok",
            },
            {
                "timestamp_utc": _iso(now - timedelta(minutes=110)),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "ok",
            },
            {
                "timestamp_utc": _iso(now),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 2_000_000,
                "completion_tokens": 0,
                "status": "ok",
            },
        ],
    )
    spend = compute_spend(log, _default_price_map(), session_gap_minutes=30)
    # Session = cost of #3 only = 2.0
    assert spend.session_usd == pytest.approx(2.0)


def test_compute_spend_no_gap(tmp_path):
    log = tmp_path / "log.jsonl"
    now = datetime.now(timezone.utc)
    _write_log(
        log,
        [
            {
                "timestamp_utc": _iso(now - timedelta(minutes=5)),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "ok",
            },
            {
                "timestamp_utc": _iso(now),
                "alias_requested": "claude-opus-4-7",
                "upstream_model": "deepseek/deepseek-v4-flash",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "status": "ok",
            },
        ],
    )
    spend = compute_spend(log, _default_price_map(), session_gap_minutes=30)
    assert spend.session_usd == pytest.approx(2.0)


def test_compute_spend_malformed_skipped(tmp_path):
    log = tmp_path / "log.jsonl"
    now = datetime.now(timezone.utc)
    good = {
        "timestamp_utc": _iso(now),
        "alias_requested": "claude-opus-4-7",
        "upstream_model": "deepseek/deepseek-v4-flash",
        "prompt_tokens": 1_000_000,
        "completion_tokens": 0,
        "status": "ok",
    }
    with log.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(good) + "\n")
        fh.write("{this is not valid json\n")
        fh.write("\n")  # empty line
        fh.write(json.dumps(good) + "\n")
    spend = compute_spend(log, _default_price_map())
    assert spend.request_count_today == 2
    assert spend.today_usd == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# estimate_preset_cost
# ---------------------------------------------------------------------------


def test_estimate_preset_cost_basic():
    role_models = {
        "advisor": "anthropic/claude-opus-4.8",
        "agent": "z-ai/glm-5.2",
        "subagent": "deepseek/deepseek-v4-flash",
    }
    pmap = {
        "anthropic/claude-opus-4.8": Pricing(10.0, 30.0, ""),
        "z-ai/glm-5.2": Pricing(2.0, 4.0, ""),
        "deepseek/deepseek-v4-flash": Pricing(1.0, 2.0, ""),
    }
    out = estimate_preset_cost(role_models, pmap)
    # 0.1*10 + 0.3*2 + 0.6*1 = 1 + 0.6 + 0.6 = 2.20
    assert out == "$2.20/1M in"


def test_estimate_preset_cost_missing_role():
    role_models = {
        "advisor": "anthropic/unknown",
        "agent": "z-ai/glm-5.2",
        "subagent": "deepseek/deepseek-v4-flash",
    }
    pmap = {
        "z-ai/glm-5.2": Pricing(2.0, 4.0, ""),
        "deepseek/deepseek-v4-flash": Pricing(1.0, 2.0, ""),
    }
    assert estimate_preset_cost(role_models, pmap) == "—"


def test_estimate_preset_cost_strips_tilde():
    role_models = {
        "advisor": "~anthropic/foo",
        "agent": "~z-ai/glm-5.2",
        "subagent": "~deepseek/deepseek-v4-flash",
    }
    pmap = {
        "anthropic/foo": Pricing(10.0, 30.0, ""),
        "z-ai/glm-5.2": Pricing(2.0, 4.0, ""),
        "deepseek/deepseek-v4-flash": Pricing(1.0, 2.0, ""),
    }
    out = estimate_preset_cost(role_models, pmap)
    assert out == "$2.20/1M in"
