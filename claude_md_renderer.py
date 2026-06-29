"""Renderer for the CLAUDE.md routing block.

Pure stdlib. Produces a marker-delimited markdown block that can be spliced
into CLAUDE.md by the integration layer (see litellm_utils.update_claude_md).
"""

from dataclasses import dataclass


_ROUTING_START = "<!-- litellm-routing-start -->"
_ROUTING_END = "<!-- litellm-routing-end -->"


@dataclass
class BudgetView:
    enabled: bool = False
    cap_usd: float = 0.0
    spent_today_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.cap_usd - self.spent_today_usd)

    @property
    def pct_used(self) -> float:
        if self.cap_usd <= 0:
            return 0.0
        return self.spent_today_usd / self.cap_usd


def render_routing_block(
    models: dict,
    preset_name: str | None = None,
    pricing_by_role: dict | None = None,
    budget: "BudgetView | None" = None,
) -> str:
    """Return the marker-delimited markdown block for CLAUDE.md."""
    advisor = models.get("advisor", "—")
    agent = models.get("agent", "—")
    subagent = models.get("subagent", "—")

    pricing_by_role = pricing_by_role or {}
    price_advisor = pricing_by_role.get("advisor", "—")
    price_agent = pricing_by_role.get("agent", "—")
    price_subagent = pricing_by_role.get("subagent", "—")

    lines = [
        _ROUTING_START,
        "| Alias | Maps to | Role | Pricing |",
        "|-------|---------|------|---------|",
        f"| claude-opus-4-8 | {advisor} | Advisor (default) | {price_advisor} |",
        f"| claude-opus-4-7 | {advisor} | Advisor | {price_advisor} |",
        f"| claude-sonnet-4-6 | {agent} | Agent | {price_agent} |",
        f"| claude-* | {subagent} | Subagent (catch-all) | {price_subagent} |",
        "",
    ]

    if preset_name is not None:
        lines.append(f"**Tier:** {preset_name}")

    if budget is not None and budget.enabled:
        pct = int(round(budget.pct_used * 100))
        lines.append(
            f"**Budget today:** ${budget.spent_today_usd:.2f} / ${budget.cap_usd:.2f} "
            f"({pct}%, ${budget.remaining_usd:.2f} left)"
        )

    lines.extend([
        "",
        "*Routing guidance for the model:*",
        "- **Advisor** is your strongest reasoner — call it before substantive work and when stuck. Use sparingly.",
        "- **Agent** is your default for active coding work — balanced cost/capability.",
        "- **Subagent** (catch-all) is cheap and fast — delegate well-scoped implementation, search, and mechanical tasks here.",
        "- When delegating to a Subagent, hand it a precise spec (function signature, I/O shapes, examples) — don't ask it to design.",
        _ROUTING_END,
    ])

    return "\n".join(lines)
