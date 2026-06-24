# Phase 0 Spike — shared-proxy + ANTHROPIC_MODEL

> Throwaway test harness for the multi-agent teams plan. Not used at runtime.

## The question

If we run **one** LiteLLM proxy hosting per-agent **namespaced aliases**
(`agentA-main`, `agentB-main`, …) and spawn **N** Claude Code terminals each
with its own `ANTHROPIC_MODEL` env var, does Claude Code actually send the
right alias in its outgoing requests?

- **Yes** → shared-proxy architecture is viable. Build Teams on top of one
  proxy with namespaced aliases. Scales to "as many agents as the user wants."
- **No**  → fall back to one proxy per agent, with a practical cap.

## How the test works

`litellm-spike.yaml` defines two aliases, **both pointing at the same cheap
deepseek-v4-flash backend**. We don't care about model behavior — we only care
about which alias the proxy sees in each terminal's request body. Each test
run costs cents at most.

`verdict.py` reads the proxy log and reports whether **both** alias names
appeared in incoming requests.

## Run it

> Requires `OPENROUTER_API_KEY` set in the proxy terminal.

1. **Terminal 1 — start the spike proxy**
   ```powershell
   cd spike
   $env:OPENROUTER_API_KEY = "sk-or-v1-..."   # if not already set
   .\start-proxy.ps1
   ```
   Leave it running. Logs stream here and also write to `spike-proxy.log`.

2. **Terminal 2 — launch the two agent terminals**
   ```powershell
   cd spike
   .\open-agentA.ps1
   .\open-agentB.ps1
   ```
   Two new PowerShell windows open, each with `ANTHROPIC_MODEL` pinned to a
   different alias.

3. **In each agent window** — fire one prompt:
   ```powershell
   claude "say hi"
   ```
   You can press Ctrl+C right after it starts replying — we only need the
   request to land in the proxy log.

4. **Read the verdict**
   ```powershell
   cd spike
   python verdict.py
   ```

## Expected good outcome

```
  ✓ agentA-main     N request line(s)
  ✓ agentB-main     N request line(s)
RESULT: Both aliases appeared in the proxy log.
=> Shared-proxy architecture is VIABLE.
```

## Cleanup

When you're done, stop the proxy (Ctrl+C in terminal 1) and you can either
keep `spike/` around as a reference or delete it — nothing in the main GUI
depends on it.
