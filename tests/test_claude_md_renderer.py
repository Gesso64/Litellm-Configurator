"""Tests for claude_md_renderer.render_routing_block."""

from claude_md_renderer import (
    BudgetView,
    render_routing_block,
    _ROUTING_START,
    _ROUTING_END,
)


MODELS = {
    "advisor": "anthropic/claude-sonnet-latest",
    "agent": "z-ai/glm-5.2",
    "subagent": "deepseek/deepseek-v4-flash",
}


def test_basic_no_pricing_no_budget():
    block = render_routing_block(MODELS)
    # All pricing columns are em-dash
    assert "| claude-opus-4-8 | anthropic/claude-sonnet-latest | Advisor (default) | — |" in block
    assert "| claude-opus-4-7 | anthropic/claude-sonnet-latest | Advisor | — |" in block
    assert "| claude-sonnet-4-6 | z-ai/glm-5.2 | Agent | — |" in block
    assert "| claude-* | deepseek/deepseek-v4-flash | Subagent (catch-all) | — |" in block
    # No tier line
    assert "**Tier:**" not in block
    # No budget line
    assert "**Budget today:**" not in block


def test_with_pricing():
    pricing = {
        "advisor": "$3 / $15 per 1M",
        "agent": "$0.50 / $1.50 per 1M",
        "subagent": "$0.10 / $0.30 per 1M",
    }
    block = render_routing_block(MODELS, pricing_by_role=pricing)
    assert "| claude-opus-4-8 | anthropic/claude-sonnet-latest | Advisor (default) | $3 / $15 per 1M |" in block
    assert "| claude-opus-4-7 | anthropic/claude-sonnet-latest | Advisor | $3 / $15 per 1M |" in block
    assert "| claude-sonnet-4-6 | z-ai/glm-5.2 | Agent | $0.50 / $1.50 per 1M |" in block
    assert "| claude-* | deepseek/deepseek-v4-flash | Subagent (catch-all) | $0.10 / $0.30 per 1M |" in block


def test_with_preset_name():
    block = render_routing_block(MODELS, preset_name="Sweet Spot")
    assert "**Tier:** Sweet Spot" in block


def test_with_budget_enabled():
    budget = BudgetView(enabled=True, cap_usd=5.0, spent_today_usd=3.0)
    block = render_routing_block(MODELS, budget=budget)
    assert "**Budget today:**" in block
    assert "$3.00 / $5.00" in block
    assert "60%" in block
    assert "$2.00 left" in block


def test_budget_disabled_omitted():
    budget = BudgetView(enabled=False, cap_usd=5.0, spent_today_usd=3.0)
    block = render_routing_block(MODELS, budget=budget)
    assert "**Budget today:**" not in block


def test_missing_models_show_dash():
    partial = {"advisor": "anthropic/claude-sonnet-latest", "subagent": "deepseek/deepseek-v4-flash"}
    block = render_routing_block(partial)
    # The agent row should have — for "Maps to"
    assert "| claude-sonnet-4-6 | — | Agent | — |" in block


def test_markers_present():
    block = render_routing_block(MODELS)
    lines = block.split("\n")
    assert lines[0] == _ROUTING_START
    assert lines[-1] == _ROUTING_END
    # No trailing newline
    assert not block.endswith("\n")
