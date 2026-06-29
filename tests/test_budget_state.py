from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from budget_state import (  # noqa: E402
    BudgetConfig,
    BudgetSignal,
    evaluate,
    load_config,
    save_config,
)


# ---------- load_config ----------

def test_load_config_missing_file(tmp_path):
    path = tmp_path / "does_not_exist.json"
    cfg = load_config(path)
    assert cfg == BudgetConfig()
    assert cfg.enabled is False
    assert cfg.cap_usd == 5.0
    assert cfg.warn_threshold == 0.8
    assert cfg.auto_downgrade is False


def test_load_config_malformed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("this is not { valid json", encoding="utf-8")
    cfg = load_config(path)
    assert cfg == BudgetConfig()


def test_load_config_partial(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"cap_usd": 12.5}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.cap_usd == 12.5
    assert cfg.enabled is False
    assert cfg.warn_threshold == 0.8
    assert cfg.auto_downgrade is False


def test_load_config_extra_keys_ignored(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text(
        json.dumps({"cap_usd": 7.0, "unknown_key": "whatever", "nested": {"a": 1}}),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.cap_usd == 7.0
    assert cfg.enabled is False


# ---------- save_config ----------

def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "budget.json"
    cfg = BudgetConfig(enabled=True, cap_usd=10.0)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.enabled is True
    assert loaded.cap_usd == 10.0
    assert loaded.warn_threshold == 0.8
    assert loaded.auto_downgrade is False


def test_save_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "deep" / "budget.json"
    assert not path.parent.exists()
    cfg = BudgetConfig(enabled=True, cap_usd=3.0)
    save_config(cfg, path)
    assert path.exists()
    assert path.parent.is_dir()


def test_save_atomic_no_partial_writes(tmp_path):
    path = tmp_path / "budget.json"
    # Pre-existing file with stale content
    path.write_text("STALE GARBAGE THAT IS LONGER THAN THE NEW CONTENT" * 10, encoding="utf-8")

    cfg = BudgetConfig(enabled=True, cap_usd=2.5, warn_threshold=0.5)
    save_config(cfg, path)

    raw = path.read_text(encoding="utf-8")
    # The file should be valid JSON matching cfg
    parsed = json.loads(raw)
    assert parsed["enabled"] is True
    assert parsed["cap_usd"] == 2.5
    assert parsed["warn_threshold"] == 0.5
    # No leftover garbage
    assert "STALE" not in raw

    # And it should round-trip cleanly
    loaded = load_config(path)
    assert loaded == cfg


# ---------- evaluate ----------

def test_evaluate_disabled():
    cfg = BudgetConfig(enabled=False, cap_usd=10.0)
    sig = evaluate(cfg, spent_today_usd=999.0)
    assert sig.level == "disabled"
    assert sig.pct_used == 0.0
    assert sig.remaining_usd == 0.0
    assert "disabled" in sig.message.lower()
    assert sig.warn_or_exceeded is False


def test_evaluate_invalid_cap():
    cfg = BudgetConfig(enabled=True, cap_usd=0.0)
    sig = evaluate(cfg, spent_today_usd=1.0)
    assert sig.level == "disabled"


def test_evaluate_ok():
    cfg = BudgetConfig(enabled=True, cap_usd=10.0, warn_threshold=0.8)
    sig = evaluate(cfg, spent_today_usd=2.0)
    assert sig.level == "ok"
    assert sig.pct_used == pytest.approx(0.2)
    assert sig.remaining_usd == pytest.approx(8.0)
    assert sig.warn_or_exceeded is False


def test_evaluate_warn():
    cfg = BudgetConfig(enabled=True, cap_usd=10.0, warn_threshold=0.8)
    sig = evaluate(cfg, spent_today_usd=8.0)
    assert sig.level == "warn"
    assert sig.warn_or_exceeded is True


def test_evaluate_warn_inside_band():
    cfg = BudgetConfig(enabled=True, cap_usd=10.0, warn_threshold=0.8)
    sig = evaluate(cfg, spent_today_usd=9.0)
    assert sig.level == "warn"
    assert sig.remaining_usd == pytest.approx(1.0)


def test_evaluate_exceeded():
    cfg = BudgetConfig(enabled=True, cap_usd=10.0, warn_threshold=0.8)
    sig = evaluate(cfg, spent_today_usd=12.5)
    assert sig.level == "exceeded"
    assert sig.remaining_usd == 0.0
    assert sig.warn_or_exceeded is True


def test_evaluate_pct_can_exceed_one():
    cfg = BudgetConfig(enabled=True, cap_usd=5.0, warn_threshold=0.8)
    sig = evaluate(cfg, spent_today_usd=10.0)
    assert sig.pct_used == pytest.approx(2.0)
    assert sig.level == "exceeded"


def test_message_contains_numbers_formatted():
    cfg = BudgetConfig(enabled=True, cap_usd=10.0, warn_threshold=0.8)

    ok_sig = evaluate(cfg, spent_today_usd=1.0)
    assert "$1.00" in ok_sig.message
    assert "$10.00" in ok_sig.message

    warn_sig = evaluate(cfg, spent_today_usd=8.0)
    assert "$8.00" in warn_sig.message
    assert "$10.00" in warn_sig.message

    exceeded_sig = evaluate(cfg, spent_today_usd=15.0)
    assert "$15.00" in exceeded_sig.message
    assert "$10.00" in exceeded_sig.message
