# Plan: Multi-Agent Teams (parallel, profile-isolated Claude Code agents)

> Status: **planned, not started.** This is a design document, not implemented code.

## Goal

Spawn multiple Claude Code CLIs in parallel from the GUI, where each agent:

- runs as its **own Claude Code process**,
- uses its **own model profile** (role → OpenRouter model mapping),
- works in its **own git worktree** (isolated branch / files),
- can be **driven interactively** by the user, and
- can **interact with the other agents** via a local MCP message-bus.

## Decisions locked in

| Question | Decision |
|----------|----------|
| Core behavior | **Parallel, isolated agents** (each in its own git worktree), not just native subagents |
| Interaction mechanism | **MCP message-bus** — agents send/receive messages directly via tool calls |
| Agent count | **No hard cap** — design must scale to "as many as the user wants" |

### Why not Claude Code's native subagents?

Claude Code already supports heterogeneous-model multi-agent via custom subagents
(`.claude/agents/*.md`, each with its own `model:` flowing through the proxy). That
covers "different models collaborating on one task" with zero new code. We are
**not** using that path because the user specifically needs **parallel, worktree-
isolated, independently-drivable processes** — which native subagents can't provide:

| Need | Native subagents | Separate CLIs (this plan) |
|------|------------------|---------------------------|
| Different model per agent | yes (with more slots) | yes |
| True parallel execution | semi-sequential | yes |
| Isolated git worktrees | no | yes |
| Independently driven interactively | no | yes |
| Per-agent MCP/tool configs | no | yes |

### Differentiator vs. existing tools (claude-squad, worktree orchestrators, Agent SDK)

Keep the build **thin**. The unique value is **per-agent model profiles + per-agent
budgets through the existing LiteLLM proxy** — not a new agent framework. Reuse the
existing pieces: `generate_yaml`, `ProxyLauncher`, the heartbeat, `open_terminal_with_env`,
the profile system, and the vision hook.

## Architecture: shared proxy, not per-agent proxies

"No cap on agents" rules out one LiteLLM proxy per agent — each proxy is a heavy
uvicorn process (hundreds of MB RAM, multi-second startup), so 6–8 of them is several
GB and a slow launch. Instead:

- **One shared LiteLLM proxy** hosts every agent's models under **unique namespaced
  aliases** (`agentA-main`, `agentA-fast`, `agentB-main`, …).
- Each agent's Claude Code is pinned to its own model names via env
  (`ANTHROPIC_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL`) so two agents requesting "their"
  model hit different backends through the **same** proxy.

**Risk to validate first (Phase 0):** this depends on Claude Code honoring those
per-instance model env vars. If it does → shared proxy. If not → fall back to
per-agent proxies with a practical cap (~2–4).

## Phases

### Phase 0 — Spike (gates the architecture)
Confirm a single proxy + two terminals with different `ANTHROPIC_MODEL` /
`ANTHROPIC_SMALL_FAST_MODEL` route to different models. Decides shared-proxy vs
per-agent-proxy before any UI is built.

### Phase 1 — Team model & scalable GUI
A Team = N agents, each `{name, models, alias-namespace, branch}`. Persist under
`~/.claude/teams/<team>.json`. New **Teams view** with a scrollable agent list
(add / remove / clone rows) — not the fixed 3-card layout, since N is open-ended.

### Phase 2 — Worktree management
Validate the target repo is a git repo; `git worktree add` per agent on
`agent/<name>`; track and clean up on teardown.

### Phase 3 — Shared-proxy generation & launch
Extend `generate_yaml` to emit all agents' namespaced aliases into one config;
launch the single proxy (+ vision hook); health-check.

### Phase 4 — Terminal spawning  → **MVP ends here**
One terminal per agent: `cd` worktree, set the shared `ANTHROPIC_BASE_URL` + that
agent's model-name env vars, launch `claude`. Phases 0–4 deliver the core:
parallel, isolated, profile-differentiated agents the user can drive.

### Phase 5 — MCP message-bus (`agent_bus.py`)
Local MCP server exposing `list_agents` / `send_message(to, body)` / `inbox`. Each
Claude Code launched with `--mcp-config` pointing at it, so agents message each
other directly. **Rate / turn limits built in from day one.**

### Phase 6 — Safety & teardown (non-negotiable at scale)
- Per-agent **budgets via LiteLLM virtual keys** (proxy hard-stops an over-spending agent)
- **Global team budget**
- Bus turn caps (default to human-gated / low caps initially)
- GUI **kill-all** button
- Proxy teardown + worktree cleanup

### Phase 7 — Tests
Team config round-trip, worktree lifecycle, shared-proxy routing, bus messaging +
limits, teardown.

## Hard warnings

- **Cost / loop risk.** Many autonomous agents messaging in parallel is where cost
  runs away fastest (message storms, loops, agents talking past each other). The
  Phase 6 guardrails are load-bearing, not polish. Default the bus to low/human-gated
  turn caps; raise only after watching a real team behave.
- **Coherence.** Keeping many parallel agents productive (not stepping on each other)
  is genuinely hard — worktree isolation helps with files, but task coordination is
  the open problem.
- **Resource ceiling.** Even with a shared proxy, N terminals + N Claude Code
  processes have real RAM/CPU limits on the host.

## Recommended starting point

Begin with **Phase 0 (the spike)** — cheap, and it decides the whole architecture
before committing to the Teams UI. Then build the **MVP (Phases 0–4)** as a clean,
self-contained milestone before layering the MCP bus (Phase 5) and guardrails (Phase 6).
