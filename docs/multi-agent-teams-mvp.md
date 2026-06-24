# Multi-Agent Teams — MVP Implementation Plan (Phases 1-4)

> Concrete, file-level plan ready to act on. Companion to [multi-agent-teams-plan.md](multi-agent-teams-plan.md) which captures the *why*. This doc captures the *what to build*.

## Where we are

- **Phase 0 done.** Shared-proxy + per-instance `ANTHROPIC_MODEL` is confirmed viable via `spike/`.
- **MVP scope (this doc):** Phases 1-4 — a team config, worktree management, one shared LiteLLM proxy hosting per-agent namespaced aliases, and one Claude Code terminal per agent. End state: the user defines a team of N agents, clicks Launch, and gets N terminal windows each running an isolated `claude` instance in its own git worktree with its own model.
- **Out of scope (deferred):** MCP message-bus (Phase 5), budget guardrails (Phase 6) — both have their own follow-on planning.

## Architecture recap

```
                       ┌──────────────────────┐
                       │ Single LiteLLM proxy │
                       │     localhost:4002   │
                       │ aliases:             │
                       │   alpha-main         │
                       │   alpha-fast         │
                       │   beta-main          │
                       │   beta-fast          │
                       └──────────┬───────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
  ┌─────▼─────┐             ┌─────▼─────┐             ┌─────▼─────┐
  │ Terminal  │             │ Terminal  │             │ Terminal  │
  │ "alpha"   │             │ "beta"    │             │ "gamma"   │
  │           │             │           │             │           │
  │ ANTHROPIC_│             │ ANTHROPIC_│             │ ANTHROPIC_│
  │ MODEL=    │             │ MODEL=    │             │ MODEL=    │
  │ alpha-main│             │ beta-main │             │ gamma-main│
  │           │             │           │             │           │
  │ worktree: │             │ worktree: │             │ worktree: │
  │ agent/    │             │ agent/    │             │ agent/    │
  │  alpha    │             │  beta     │             │  gamma    │
  └───────────┘             └───────────┘             └───────────┘
```

One proxy. N agents. Each terminal pinned to its own alias via env; each working in its own git worktree.

## Data model

### Team JSON — `~/.claude/teams/<team-name>.json`

```jsonc
{
  "name": "demo-team",
  "port": 4002,                  // shared-proxy port; default 4002 to not collide with single-mode 4001
  "repo_dir": "C:/path/to/repo", // git repo the worktrees branch from
  "agents": [
    {
      "name": "alpha",                                // unique within team; used in alias names + branch
      "main_model":  "anthropic/claude-opus-4.8",     // backs alpha-main
      "fast_model":  "deepseek/deepseek-v4-flash",    // backs alpha-fast
      "branch": "agent/alpha"                         // defaults to agent/<name>
    },
    {
      "name": "beta",
      "main_model": "z-ai/glm-5.2",
      "fast_model": "deepseek/deepseek-v4-flash",
      "branch": "agent/beta"
    }
  ],
  "vision_fallback": "auto",     // reuses existing single-mode setting; "auto" picks an image-capable model from the team
  "created": "2026-06-24T00:00:00"
}
```

### Conventions

| Convention | Value |
|------------|-------|
| Per-agent main alias | `<agent>-main` (e.g. `alpha-main`) |
| Per-agent fast alias | `<agent>-fast` |
| Default branch | `agent/<agent>` |
| Default worktree path | `<repo_dir>/.agent-worktrees/<agent>` |
| Default shared-proxy port | `4002` (single-mode keeps `4001`) |

## Files to add / change

### New

| File | Purpose |
|------|---------|
| `teams_utils.py` | Team JSON I/O; generate YAML for N agents; worktree create/remove helpers |
| `docs/multi-agent-teams-mvp.md` | This document |

### Changed

| File | Change |
|------|--------|
| `litellm_utils.py` | Factor `generate_yaml` so it can also emit a team config (N agents × 2 aliases); existing single-mode call still works |
| `start-litellm-gui.py` | Add **Teams view** (menu: View → Teams, or a tab/toggle), keep single-mode view intact for now; new launcher class `TeamLauncher`; new menu actions: Save Team, Launch Team, Stop Team |

> Decision: keep single-mode and teams as two parallel surfaces, not a merge. The model selector card UI doesn't generalize cleanly to N>3 agents — Teams needs its own scrollable list. Existing users keep their flow.

## Phase 1 — Team model & GUI

### 1.1 `teams_utils.py` skeleton

```python
TEAMS_DIR = CONFIG_DIR / "teams"

def team_path(name: str) -> Path: ...
def save_team(team: dict) -> None: ...
def load_team(name: str) -> dict: ...
def list_teams() -> list[tuple[str, dict]]: ...
def delete_team(name: str) -> None: ...

def validate_team(team: dict) -> list[str]:
    """Return a list of human-readable errors; [] = valid.
       Checks: name non-empty, agents non-empty, agent names unique + safe
       (^[a-z][a-z0-9-]{0,30}$), repo_dir is a git repo, no branch collisions."""
```

### 1.2 GUI surface

- **New menu**: `View → Teams…` opens a Teams window (modeless QDialog or new tab on the main window).
- **Teams window layout**:
  - Left rail: list of saved teams + New/Delete buttons.
  - Right side, top: team-level fields (name, repo dir + Browse, shared port, vision fallback).
  - Right side, middle: **scrollable agent rows**. Each row =
    `[ name ] [ main model: search-combo ] [ fast model: search-combo ] [ branch ] [ × ]`.
  - Right side, bottom: `+ Add Agent` and `Clone Selected`.
  - Footer: `Save Team` / `Launch Team` / `Stop Team` / `Kill Team`.
- **Model search-combo**: reuse the existing `ModelSearchWidget` filter+search logic, but as a smaller inline picker (drop the list pane; use a popup). If that's too much for MVP, render it as a `QComboBox` populated from `self._models` with the existing sort/filter applied — searchable via the combo's built-in `setEditable(True)`.

### 1.3 Persistence

- On every team-form edit, write to `~/.claude/teams/<name>.json` (debounced, same pattern as the session save).
- On team rename: write new file, delete old; refuse if old has running worktrees.

## Phase 2 — Worktree management

### 2.1 New helpers in `teams_utils.py`

```python
def ensure_worktrees(team: dict) -> list[Path]:
    """For each agent, ensure repo/.agent-worktrees/<name> exists on the
       agent's branch. Creates branch from current HEAD if missing.
       Returns the worktree paths. Raises on non-git repo or dirty checkout."""

def remove_worktrees(team: dict, *, prune_branches: bool = False) -> list[str]:
    """git worktree remove each path. If prune_branches, also delete the
       agent branch *only if* it has no unmerged commits. Returns list of
       removed paths; collects warnings for skipped ones."""
```

### 2.2 Safety rules

- **Refuse** to launch if `repo_dir` isn't a git repo (`git rev-parse --git-dir`).
- **Refuse** to remove a worktree with uncommitted changes (`git status --porcelain` in the worktree). The GUI's Stop Team should show what's blocking and offer a "Force" confirmation.
- **Worktree layout**: `<repo>/.agent-worktrees/<agent>/`. Add to `.gitignore` automatically on first team launch (one-line append, idempotent).

## Phase 3 — Shared-proxy launch

### 3.1 YAML generation

Extend `litellm_utils.generate_yaml` (or add a `generate_team_yaml`) so the model_list contains 2 entries per agent:

```yaml
model_list:
  - model_name: alpha-main
    litellm_params: { model: openrouter/<alpha.main_model>, api_key: os.environ/OPENROUTER_API_KEY }
    model_info: { supports_vision: <bool> }
  - model_name: alpha-fast
    litellm_params: { model: openrouter/<alpha.fast_model>, api_key: os.environ/OPENROUTER_API_KEY }
    model_info: { supports_vision: <bool> }
  - model_name: beta-main
    ...
  # vision-fallback entry as today
litellm_settings:
  callbacks: ["vision_router.instance"]
```

### 3.2 Vision routing reuse

The existing `vision_router.json` sidecar (`vision_map` + `fallback_alias`) generalizes cleanly: write one entry per `<agent>-main` and `<agent>-fast` based on each backing model's vision support. The hook needs no changes.

### 3.3 Launcher class

In `start-litellm-gui.py`, a new `TeamLauncher(QObject)` that:

1. Validates the team (calls `validate_team`).
2. Ensures worktrees exist (`ensure_worktrees`).
3. Writes the team YAML to `~/.claude/teams/<name>.yaml` (separate from the single-mode YAML).
4. Deploys `vision_router.py` (existing helper).
5. Launches **one** LiteLLM proxy on `team.port`, same env hygiene as `ProxyLauncher` (`PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`, prepend `CONFIG_DIR` to `PYTHONPATH`).
6. Polls `/health/liveliness` until ready or 30s timeout.
7. Emits `ready` (port) or `failed` (err_text).

Heartbeat (Phase 5 of the single-mode polish) generalizes by simply polling the team's one port.

## Phase 4 — Terminal spawning

For each agent in the team, open a terminal with this env:

```bash
ANTHROPIC_BASE_URL=http://localhost:<team.port>
ANTHROPIC_API_KEY=sk-local-fake
ANTHROPIC_MODEL=<agent>-main
ANTHROPIC_SMALL_FAST_MODEL=<agent>-fast
```

and `cd` into the agent's worktree, then `claude` (no `--bare` in MVP — `--bare` was the spike-only safety net; real interactive sessions want OAuth/keychain available).

Reuse `open_terminal_with_env` after extending its signature to accept arbitrary `extra_env: dict` and the working directory override. Three platform branches stay as-is.

## UI mock (text)

```
┌─ Teams ─────────────────────────────────────────────────────────────┐
│ Teams         │ Name       [ demo-team        ]                     │
│ ─────────     │ Repo dir   [ C:/proj/foo            ] [ Browse… ]   │
│ ★ demo-team   │ Port       [ 4002 ]   Vision fallback [ Auto   ▾ ]  │
│   review-trio │ ──────────────────────────────────────────────────  │
│   experiments │ Agents:                                              │
│               │  ▸ alpha   main [ anthropic/opus  ▾ ]                │
│ ─────────     │            fast [ deepseek/flash  ▾ ]                │
│ [+ New]       │            branch [ agent/alpha ]              [×]   │
│ [Delete]      │  ▸ beta    main [ z-ai/glm-5.2   ▾ ]                │
│               │            fast [ deepseek/flash  ▾ ]                │
│               │            branch [ agent/beta  ]               [×]  │
│               │  [+ Add Agent] [Clone Selected]                      │
│               │ ──────────────────────────────────────────────────  │
│               │ Status: ● Stopped     [Launch Team] [Stop] [Kill]    │
└─────────────────────────────────────────────────────────────────────┘
```

## Tests

| Layer | Test |
|-------|------|
| `teams_utils.save/load_team` | Round-trip JSON, name normalization, validate errors |
| `validate_team` | Empty name, duplicate agent names, missing repo, invalid branch chars |
| `ensure_worktrees` | Creates new branch + worktree from clean HEAD; reuses existing; refuses non-git dir |
| `generate_team_yaml` | N agents → 2N+1 entries (main, fast, vision-fallback); vision_map correct |
| `TeamLauncher` (offline) | Mock subprocess; verify env + PYTHONPATH + command line are what we expect |
| Integration | Two-agent demo team, real LiteLLM proxy (cheap deepseek backend), one `claude -p "hi"` per agent terminal, assert each request body shows the right alias (extension of the Phase 0 spike) |

## Open decisions before coding

1. **Two aliases per agent (`-main`/`-fast`) vs one?** Recommend two — Claude Code uses `ANTHROPIC_SMALL_FAST_MODEL` for tool calls, summaries, etc. and forcing them onto the main model is wasteful. The MVP YAML and validator should require both, even if the user picks the same backend for both.
2. **Worktree dir inside repo (`.agent-worktrees/`) vs outside?** Inside is simpler (one path concept) and shows up in the host repo's `git worktree list`, which helps debugging. Add to `.gitignore` automatically. *Decision: inside, with auto `.gitignore` entry.*
3. **Built-in team presets?** Skip for MVP. Users save their own.
4. **Stop semantics.** Stop = kill proxy + close terminals; worktrees stay (so in-progress work is preserved). Kill = Stop + remove worktrees (with the dirty-tree refusal above). *Decision: that split.*
5. **Single-mode vs teams view coexistence.** Both stay. The Teams view is an additional surface, not a replacement. Single-mode is still the simplest way to point one `claude` at one model set.

## Out of scope (track separately)

- **Phase 5 — MCP message-bus** (`agent_bus.py`): agents talk to each other directly. Needs its own design pass with rate/turn caps.
- **Phase 6 — Budget guardrails**: per-agent virtual keys, per-team budget. Non-negotiable for autonomous bus use; less critical for the MVP where a human watches each terminal.
- **Phase 7 — Tests above + CI.**

## Recommended starting order

1. `teams_utils.py` data layer + tests (no GUI yet, can be exercised from `python -c`).
2. `generate_team_yaml` + extension of the existing spike to a 3-agent real launch (cheap deepseek backend, manual terminal opening).
3. GUI Teams view + Launch button.
4. Worktree integration.
5. Polish, heartbeat reuse, cleanup story.

Steps 1-2 are valuable independent of the GUI — they're the data + proxy core. If you only have an afternoon, do those and run the spike-shaped manual launch to prove the foundation before painting UI.
