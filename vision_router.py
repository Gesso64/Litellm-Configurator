"""LiteLLM proxy pre-call hook: reroute image requests to a vision-capable model.

When Claude Code sends a request containing images to a role whose model can't
handle images, this hook rewrites the target model to a configured vision-capable
fallback *before* the call is made — avoiding an upstream API error.

Configuration lives in ``vision-router.json`` next to this file (written by
``litellm_utils.generate_yaml``):

    {
      "enabled": true,
      "vision_map": {"claude-opus-4-7": true, "claude-sonnet-4-6": false, "claude-*": false},
      "fallback_alias": "vision-fallback"   // or null when disabled / "Off"
    }

The hook is registered in the generated LiteLLM config via:

    litellm_settings:
      callbacks: ["vision_router.instance"]

It fails open: any error in loading config or inspecting the request leaves the
request untouched so the proxy keeps working.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

try:
    from litellm.integrations.custom_logger import CustomLogger
except Exception:  # pragma: no cover - litellm always present in the proxy env
    class CustomLogger:  # type: ignore
        """Fallback base so this module imports even without litellm installed."""

        pass


log = logging.getLogger("vision_router")

# Content-part type markers that indicate an image, across Anthropic and OpenAI shapes.
_IMAGE_TYPES = {"image", "image_url", "input_image"}

_CONFIG_NAME = "vision-router.json"


def _config_path() -> Path:
    return Path(__file__).resolve().parent / _CONFIG_NAME


def _part_is_image(part) -> bool:
    if not isinstance(part, dict):
        return False
    ptype = part.get("type")
    if ptype in _IMAGE_TYPES:
        return True
    # Defensive: some shapes omit an explicit type but carry image payload keys.
    if "image_url" in part or "source" in part:
        return True
    return False


def _messages_have_image(messages) -> bool:
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if _part_is_image(part):
                    return True
    return False


class VisionRouter(CustomLogger):
    """Reroutes image-bearing requests away from non-vision models."""

    def __init__(self) -> None:
        super().__init__()
        self._mtime: float | None = None
        self._enabled = False
        self._vision_map: dict[str, bool] = {}
        self._fallback_alias: str | None = None
        self._load_config()

    # ── config ───────────────────────────────────────────────────────

    def _load_config(self) -> None:
        path = _config_path()
        try:
            stat = path.stat()
        except OSError:
            # No sidecar → feature off.
            self._enabled = False
            self._fallback_alias = None
            self._vision_map = {}
            self._mtime = None
            return
        if self._mtime is not None and stat.st_mtime == self._mtime:
            return  # unchanged since last read
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._enabled = bool(data.get("enabled", False))
            self._vision_map = dict(data.get("vision_map", {}))
            fb = data.get("fallback_alias")
            self._fallback_alias = fb if isinstance(fb, str) and fb else None
            self._mtime = stat.st_mtime
        except Exception as exc:  # malformed → fail open (disabled)
            log.warning("vision_router: failed to load %s: %s", path, exc)
            self._enabled = False
            self._fallback_alias = None
            self._vision_map = {}

    # ── capability lookup ─────────────────────────────────────────────

    def _supports_vision(self, model: str) -> bool:
        """True if the requested model handles images. Unknown models assume True
        so we never reroute something we can't reason about."""
        if model in self._vision_map:
            return self._vision_map[model]
        for key, supports in self._vision_map.items():
            if key.endswith("*") and model.startswith(key[:-1]):
                return supports
        return True

    # ── the hook ───────────────────────────────────────────────────────

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        # Diagnostic: log the FULL request shape so we can diff a failing one against curl.
        try:
            import json as _json
            from pathlib import Path as _Path
            from datetime import datetime, timezone
            dbg = _Path.home() / ".claude" / "litellm-precall-full.jsonl"
            if isinstance(data, dict):
                # Pull headers (LiteLLM nests them in metadata.headers)
                md = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
                headers = md.get("headers") if isinstance(md, dict) else None
                # Redact obvious secrets in headers before persisting.
                if isinstance(headers, dict):
                    headers = {
                        k: ("***REDACTED***" if any(s in (k or "").lower() for s in ("api-key","api_key","authorization","x-key")) else v)
                        for k, v in headers.items()
                    }
                # Make a copy of data with messages trimmed (keep first message only, length-marker for rest)
                _data_copy = {}
                for k, v in data.items():
                    if k == "messages" and isinstance(v, list):
                        _data_copy["messages_count"] = len(v)
                        _data_copy["messages_first"] = v[0] if v else None
                        _data_copy["messages_last"] = v[-1] if len(v) > 1 else None
                    elif k == "tools" and isinstance(v, list):
                        _data_copy["tools_count"] = len(v)
                        _data_copy["tools_full"] = [
                            {
                                "name": (t.get("name") if isinstance(t, dict) else None),
                                "type": (t.get("type") if isinstance(t, dict) else None),
                                "model": (t.get("model") if isinstance(t, dict) else None),
                                "api_base": (t.get("api_base") if isinstance(t, dict) else None),
                                "api_key_present": (bool(t.get("api_key")) if isinstance(t, dict) else None),
                            }
                            for t in v
                        ]
                    else:
                        _data_copy[k] = v
                snapshot = {
                    "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "call_type": call_type,
                    "headers": headers,
                    "data": _data_copy,
                }
                with dbg.open("a", encoding="utf-8") as f:
                    f.write(_json.dumps(snapshot, default=str) + "\n")
        except Exception:
            pass
        # ── advisor-tool routing fix ──────────────────────────────────
        # LiteLLM 1.89.3 has a built-in AdvisorOrchestrationHandler that
        # intercepts requests containing an advisor_20260301 tool. When that
        # interceptor makes its sub-call to the advisor model, it ignores
        # ANTHROPIC_BASE_URL and goes direct to api.anthropic.com — using
        # whatever ambient api_key it finds (our master key 'sk-local-fake')
        # → 401 Unauthorized. The interceptor only routes correctly if the
        # advisor tool definition itself carries api_base + api_key. Claude
        # Code does not set them. Inject them here so the sub-call comes
        # back to *this* proxy and routes through the configured deployment.
        try:
            if isinstance(data, dict):
                _tools = data.get("tools")
                if isinstance(_tools, list):
                    for _t in _tools:
                        if not isinstance(_t, dict):
                            continue
                        if _t.get("type") == "advisor_20260301":
                            if not _t.get("api_base"):
                                _t["api_base"] = "http://localhost:4001"
                            if not _t.get("api_key"):
                                _t["api_key"] = "sk-local-fake"
        except Exception:
            pass

        try:
            self._load_config()
            if not self._enabled or not self._fallback_alias:
                return data
            if not isinstance(data, dict):
                return data

            model = data.get("model")
            if not isinstance(model, str) or not model:
                return data
            # Already targeting the vision fallback — nothing to do.
            if model == self._fallback_alias:
                return data

            if not _messages_have_image(data.get("messages")):
                return data
            if self._supports_vision(model):
                return data

            data["model"] = self._fallback_alias
            log.info(
                "vision_router: rerouted image request from '%s' to '%s' (call_type=%s)",
                model, self._fallback_alias, call_type,
            )
        except Exception as exc:  # never break the request path
            log.warning("vision_router: pre-call hook error (passing through): %s", exc)
        return data


# Registered in the proxy config as "vision_router.instance".
instance = VisionRouter()
