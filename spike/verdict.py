"""Phase 0 spike — read the verdict from the proxy log.

Looks for the model name in incoming requests. If both 'agentA-main' and
'agentB-main' appear, Claude Code is honoring per-terminal ANTHROPIC_MODEL
and the shared-proxy architecture is viable.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LOG = Path(__file__).parent / "spike-proxy.log"

# LiteLLM logs the incoming model in a few forms across versions. Match any
# line that pins a literal model name we care about. Patterns are deliberate-
# ly loose so a small log-format change doesn't make the verdict misleading.
TARGETS = ("agentA-main", "agentB-main")


def main() -> int:
    if not LOG.exists():
        print(f"ERROR: {LOG} not found. Run start-proxy.ps1 first.", file=sys.stderr)
        return 2

    text = LOG.read_text(encoding="utf-8", errors="replace")
    counts = {t: 0 for t in TARGETS}
    examples: dict[str, str] = {}

    # Count occurrences in any line that looks like a request, with a small
    # snippet captured for the report.
    for line in text.splitlines():
        for target in TARGETS:
            # Quoted ("model": "agentA-main") or bare (model=agentA-main).
            if re.search(rf'["\']?model["\']?\s*[:=]\s*["\']?{re.escape(target)}\b', line):
                counts[target] += 1
                if target not in examples:
                    examples[target] = line.strip()[:200]

    print("=" * 70)
    print("Phase 0 spike verdict")
    print("=" * 70)
    for target in TARGETS:
        marker = "[ok]" if counts[target] > 0 else "[--]"
        print(f"  {marker} {target:14}  {counts[target]} request line(s)")
        if target in examples:
            print(f"      sample: {examples[target]}")
    print()

    if all(counts[t] > 0 for t in TARGETS):
        print("RESULT: Both aliases appeared in the proxy log.")
        print("=> Shared-proxy architecture is VIABLE.")
        print("   Build Teams on top of one LiteLLM proxy with namespaced aliases.")
        return 0
    if any(counts[t] > 0 for t in TARGETS):
        print("RESULT: Only one alias was observed.")
        print("=> Make sure you ran a `claude` command in BOTH terminal windows.")
        return 1
    print("RESULT: Neither alias appeared.")
    print("=> Either no claude command was run, or the proxy didn't receive any")
    print("   request. Confirm the proxy is up on :4099 and try again.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
