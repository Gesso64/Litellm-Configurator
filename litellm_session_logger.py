"""LiteLLM proxy post-call hook: append one JSONL line per request.

Writes to ~/.claude/litellm-session-log.jsonl. Each line:
  timestamp_utc, request_id, alias_requested, upstream_model,
  prompt_tokens, completion_tokens, latency_ms, status, error, session_id,
  user, ip, tool_hallucination

tool_hallucination: true when the request included tools but the model
returned text-only output containing phrases that deny tool availability.
This detects the silent failure mode where a proxied non-Anthropic model
ignores tool schemas under long context and hallucinates refusal text.
Flagged calls are also written to ~/.claude/litellm-tool-hallucination.jsonl
with a text snippet for diagnosis.

Registered in the proxy config via:

    litellm_settings:
      callbacks: ["litellm_session_logger.instance", ...]

Fails open: any exception in the hook is swallowed so the request path is
never broken.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from litellm.integrations.custom_logger import CustomLogger
except Exception:  # pragma: no cover
    class CustomLogger:  # type: ignore
        pass


log = logging.getLogger("litellm_session_logger")

LOG_PATH = Path(os.environ.get(
    "LITELLM_SESSION_LOG",
    str(Path.home() / ".claude" / "litellm-session-log.jsonl"),
))
HALLUCINATION_LOG_PATH = LOG_PATH.parent / "litellm-tool-hallucination.jsonl"

# When a request has tools AND estimated prompt tokens exceed this threshold,
# the pre-call hook swaps the model to TOOL_CONTEXT_FALLBACK_MODEL so that
# a reliable model handles the long-context agentic call instead of a budget
# model that silently drops tool calls.
TOOL_CONTEXT_THRESHOLD = int(os.environ.get("TOOL_CONTEXT_THRESHOLD", "120000"))
TOOL_CONTEXT_FALLBACK_MODEL = os.environ.get(
    "TOOL_CONTEXT_FALLBACK_MODEL",
    "claude-opus-4-7",  # already in every YAML → openrouter/anthropic/claude-opus-4.6
)

# Phrases that indicate a model denied tool use in plain text.
# Only flagged when (a) the request included tools AND (b) response had no tool calls.
_TOOL_DENIAL_PHRASES = [
    "the tool is not available",
    "tools are not available",
    "tool isn't available",
    "i don't have the necessary tools",
    "i don't have access to the",
    "i am unable to directly modify",
    "i can't seem to modify",
    "cannot use the",
    "i'm unable to use",
    "unable to directly",
    "edit tool",        # catches "the edit tool is not available" etc.
    "write tool",
    "don't have the ability to",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _request_had_tools(kwargs: dict) -> bool:
    """Return True if the original request body contained a non-empty tools list."""
    try:
        psr = kwargs.get("proxy_server_request") or {}
        body = psr.get("body") if isinstance(psr, dict) else None
        if isinstance(body, dict):
            tools = body.get("tools")
            return bool(tools and isinstance(tools, list))
    except Exception:
        pass
    return False


def _extract_response_text(response_obj) -> str:
    """Pull all text content out of a litellm ModelResponse."""
    try:
        choices = getattr(response_obj, "choices", None) or []
        if not choices:
            return ""
        msg = choices[0].message
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                elif getattr(block, "type", None) == "text":
                    parts.append(getattr(block, "text", ""))
            return " ".join(parts)
    except Exception:
        pass
    return ""


def _response_has_tool_call(response_obj) -> bool:
    """Return True if the response contains any tool_use / tool_calls blocks."""
    try:
        choices = getattr(response_obj, "choices", None) or []
        if not choices:
            return False
        msg = choices[0].message
        # OpenAI format
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            return True
        # Anthropic native content-block format
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                t = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                if t == "tool_use":
                    return True
    except Exception:
        pass
    return False


def _detect_tool_hallucination(kwargs: dict, response_obj) -> tuple[bool, str | None]:
    """Return (detected, matched_phrase) for silent tool-calling failures.

    Fires when: tools were in the request, model returned no tool calls,
    AND the response text contains a known denial phrase.
    """
    try:
        if not _request_had_tools(kwargs):
            return False, None
        if _response_has_tool_call(response_obj):
            return False, None
        text = _extract_response_text(response_obj).lower()
        if not text:
            return False, None
        for phrase in _TOOL_DENIAL_PHRASES:
            if phrase in text:
                return True, phrase
    except Exception:
        pass
    return False, None


_SESSION_HEADER_NAMES = ("x-session-id", "x-claude-session-id", "x-litellm-session-id")


def _scan_headers(headers, candidates=_SESSION_HEADER_NAMES) -> str | None:
    if not isinstance(headers, dict):
        return None
    # Build a case-insensitive view to handle httpx/uvicorn lowercasing.
    lower = {k.lower(): v for k, v in headers.items() if isinstance(k, str)}
    for c in candidates:
        v = lower.get(c.lower())
        if v:
            return str(v)
    return None


def _extract_session_id(kwargs: dict) -> str | None:
    """Best-effort: pull a session id from metadata.headers or proxy_server_request.headers."""
    lp = kwargs.get("litellm_params") or {}
    md = (lp.get("metadata") if isinstance(lp, dict) else None) or kwargs.get("metadata") or {}
    if isinstance(md, dict):
        # Direct metadata key (e.g. when the client passes metadata.session_id explicitly)
        for key in ("session_id", "claude_session_id"):
            v = md.get(key)
            if v:
                return str(v)
        sid = _scan_headers(md.get("headers"))
        if sid:
            return sid
        sid = _scan_headers(md.get("requester_metadata"))
        if sid:
            return sid
    psr = kwargs.get("proxy_server_request") or {}
    if isinstance(psr, dict):
        sid = _scan_headers(psr.get("headers"))
        if sid:
            return sid
    return None


class SessionLogger(CustomLogger):
    """Append-only JSONL logger of every completion through the proxy."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._context_swapped: set[str] = set()  # call_ids that were model-swapped pre-call
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning("session_logger: cannot create log dir: %s", exc)

    def _write_hallucination(self, kwargs: dict, response_obj, matched_phrase: str | None) -> None:
        """Write a detailed record to the hallucination log for post-mortem."""
        try:
            text_snippet = _extract_response_text(response_obj)[:500]
            psr = kwargs.get("proxy_server_request") or {}
            body = psr.get("body") if isinstance(psr, dict) else {}
            tool_names = [t.get("name") for t in (body.get("tools") or []) if isinstance(t, dict)] if isinstance(body, dict) else []
            upstream = kwargs.get("model") or _safe_get(kwargs, "litellm_params", "model")
            usage = {}
            if hasattr(response_obj, "usage"):
                try:
                    u = response_obj.usage
                    usage = u.model_dump() if hasattr(u, "model_dump") else dict(u or {})
                except Exception:
                    pass
            entry = {
                "ts": _now_iso(),
                "upstream_model": upstream,
                "matched_phrase": matched_phrase,
                "prompt_tokens": usage.get("prompt_tokens") if isinstance(usage, dict) else None,
                "tools_in_request": tool_names,
                "response_text_snippet": text_snippet,
                "request_id": kwargs.get("litellm_call_id"),
            }
            line = json.dumps(entry, default=str, ensure_ascii=False)
            with self._lock:
                with HALLUCINATION_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as exc:
            log.warning("session_logger: hallucination write failed: %s", exc)

    def _write(self, entry: dict) -> None:
        try:
            line = json.dumps(entry, default=str, ensure_ascii=False)
            with self._lock:
                with LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as exc:
            log.warning("session_logger: write failed: %s", exc)

    def _build_entry(self, kwargs: dict, response_obj, start_time, end_time, status: str, error: str | None, tool_hallucination: bool | None = None) -> dict:
        try:
            latency_ms = (end_time - start_time).total_seconds() * 1000 if start_time and end_time else None
        except Exception:
            latency_ms = None

        # In LiteLLM callbacks, kwargs["model"] is the upstream model after routing
        # (e.g. "~anthropic/claude-sonnet-latest"); the alias the client asked for lives
        # at litellm_params.metadata.model_group.
        upstream_model = kwargs.get("model") or _safe_get(kwargs, "litellm_params", "model")
        if isinstance(upstream_model, str) and upstream_model.startswith("openrouter/"):
            upstream_model = upstream_model[len("openrouter/"):]

        alias_requested = (
            _safe_get(kwargs, "litellm_params", "metadata", "model_group")
            or _safe_get(kwargs, "litellm_params", "metadata", "lc_alias")
            or kwargs.get("model_group")
            or _safe_get(kwargs, "proxy_server_request", "body", "model")
        )

        usage = {}
        if hasattr(response_obj, "usage"):
            try:
                u = response_obj.usage
                usage = u.model_dump() if hasattr(u, "model_dump") else dict(u or {})
            except Exception:
                usage = {}
        elif isinstance(response_obj, dict):
            usage = response_obj.get("usage") or {}

        request_id = (
            kwargs.get("litellm_call_id")
            or _safe_get(kwargs, "litellm_params", "litellm_call_id")
            or (response_obj.id if hasattr(response_obj, "id") else None)
        )

        psr = kwargs.get("proxy_server_request") or {}
        user = _safe_get(psr, "body", "user") or kwargs.get("user")

        cost = kwargs.get("response_cost")
        try:
            cost = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost = None

        return {
            "ts": _now_iso(),
            "status": status,
            "alias_requested": alias_requested,
            "upstream_model": upstream_model,
            "prompt_tokens": usage.get("prompt_tokens") if isinstance(usage, dict) else None,
            "completion_tokens": usage.get("completion_tokens") if isinstance(usage, dict) else None,
            "total_tokens": usage.get("total_tokens") if isinstance(usage, dict) else None,
            "cost_usd": cost,
            "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
            "request_id": request_id,
            "session_id": _extract_session_id(kwargs),
            "user": user,
            "error": error,
            "call_type": kwargs.get("call_type"),
            "tool_hallucination": tool_hallucination,
            "context_fallback": True if kwargs.get("litellm_call_id") in self._context_swapped else None,
        }

    # ── pre-call hook: context-aware model swap ───────────────────────

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        """Swap to a reliable fallback model when context is long and tools are present.

        Budget models silently drop tool calls above ~120k tokens. By swapping
        here — before the call is made — we prevent the failure entirely rather
        than just logging it after the fact.
        """
        try:
            if call_type != "completion":
                return data
            tools = data.get("tools")
            if not tools:
                return data
            messages = data.get("messages") or []
            char_count = sum(
                len(str(m.get("content") or "")) for m in messages
                if isinstance(m, dict)
            )
            estimated_tokens = char_count // 4
            if estimated_tokens >= TOOL_CONTEXT_THRESHOLD:
                original_model = data.get("model", "?")
                data["model"] = TOOL_CONTEXT_FALLBACK_MODEL
                call_id = data.get("litellm_call_id") or data.get("request_id")
                if call_id:
                    self._context_swapped.add(call_id)
                    if len(self._context_swapped) > 500:
                        # Prevent unbounded growth for long-running proxy processes
                        self._context_swapped = set(list(self._context_swapped)[-250:])
                log.warning(
                    "context_fallback: %s → %s (~%dk tokens, tools present)",
                    original_model, TOOL_CONTEXT_FALLBACK_MODEL, estimated_tokens // 1000,
                )
        except Exception as exc:
            log.warning("context_fallback: pre_call_hook error: %s", exc)
        return data

    # ── sync hooks (LiteLLM calls these directly for non-async paths) ─

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        try:
            # One-shot debug dump per call_type so we capture both OpenAI and Anthropic paths.
            try:
                call_type = kwargs.get("call_type") or "unknown"
                suffix = f"-{call_type}" if call_type != "unknown" else ""
                dump_path = Path.home() / ".claude" / f"litellm-kwargs-dump{suffix}.json"
                if not dump_path.exists():
                    keys = {k: type(v).__name__ for k, v in kwargs.items()}
                    lp = kwargs.get("litellm_params") or {}
                    md = (lp.get("metadata") or {}) if isinstance(lp, dict) else {}
                    psr = kwargs.get("proxy_server_request") or {}
                    psr_keys = list(psr.keys()) if isinstance(psr, dict) else []
                    psr_body = (psr.get("body") if isinstance(psr, dict) else None) or {}
                    psr_headers = (psr.get("headers") if isinstance(psr, dict) else None) or {}
                    md_headers = md.get("headers") if isinstance(md, dict) else None
                    dump = {
                        "model": kwargs.get("model"),
                        "metadata.model_group": md.get("model_group") if isinstance(md, dict) else None,
                        "metadata.headers": md_headers,
                        "metadata.requester_metadata": md.get("requester_metadata") if isinstance(md, dict) else None,
                        "proxy_server_request": psr,
                    }
                    dump_path.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
            except Exception:
                pass
            hallucination, matched_phrase = _detect_tool_hallucination(kwargs, response_obj)
            self._write(self._build_entry(kwargs, response_obj, start_time, end_time, "ok", None, tool_hallucination=hallucination or None))
            if hallucination:
                self._write_hallucination(kwargs, response_obj, matched_phrase)
        except Exception as exc:
            log.warning("session_logger: success hook error: %s", exc)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        try:
            err = None
            if isinstance(response_obj, Exception):
                err = f"{type(response_obj).__name__}: {response_obj}"
            elif response_obj is not None:
                err = str(response_obj)[:300]

            # One-shot dump of full kwargs + headers/body on first failure.
            try:
                dump_path = Path.home() / ".claude" / "litellm-failure-dump.json"
                if not dump_path.exists():
                    lp = kwargs.get("litellm_params") or {}
                    md = (lp.get("metadata") or {}) if isinstance(lp, dict) else {}
                    psr = kwargs.get("proxy_server_request") or {}
                    md_headers = md.get("headers") if isinstance(md, dict) else None
                    # Redact obvious key fields before writing.
                    def _redact(d):
                        if not isinstance(d, dict):
                            return d
                        out = {}
                        for k, v in d.items():
                            if isinstance(k, str) and any(s in k.lower() for s in ("api-key","api_key","authorization")):
                                out[k] = "***REDACTED***"
                            else:
                                out[k] = v
                        return out
                    dump = {
                        "error": err,
                        "kwargs.model": kwargs.get("model"),
                        "kwargs.custom_llm_provider": kwargs.get("custom_llm_provider"),
                        "kwargs.api_base": kwargs.get("api_base"),
                        "kwargs.api_key_present": bool(kwargs.get("api_key")),
                        "litellm_params.model": lp.get("model") if isinstance(lp, dict) else None,
                        "litellm_params.api_base": lp.get("api_base") if isinstance(lp, dict) else None,
                        "litellm_params.custom_llm_provider": lp.get("custom_llm_provider") if isinstance(lp, dict) else None,
                        "metadata.model_group": md.get("model_group") if isinstance(md, dict) else None,
                        "metadata.deployment": md.get("deployment") if isinstance(md, dict) else None,
                        "metadata.endpoint": md.get("endpoint") if isinstance(md, dict) else None,
                        "metadata.headers": _redact(md_headers),
                        "proxy_server_request.url": psr.get("url") if isinstance(psr, dict) else None,
                        "proxy_server_request.headers": _redact(psr.get("headers") if isinstance(psr, dict) else None),
                        "proxy_server_request.body_keys": list((psr.get("body") if isinstance(psr, dict) else {}).keys())
                            if isinstance(psr, dict) and isinstance(psr.get("body"), dict) else None,
                        "proxy_server_request.body.model": (psr.get("body") if isinstance(psr, dict) else {}).get("model")
                            if isinstance(psr, dict) and isinstance(psr.get("body"), dict) else None,
                        "proxy_server_request.body.beta_field": (psr.get("body") if isinstance(psr, dict) else {}).get("anthropic_beta")
                            if isinstance(psr, dict) and isinstance(psr.get("body"), dict) else None,
                    }
                    dump_path.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
            except Exception as dump_exc:
                log.warning("session_logger: failure dump error: %s", dump_exc)

            self._write(self._build_entry(kwargs, response_obj, start_time, end_time, "error", err))
        except Exception as exc:
            log.warning("session_logger: failure hook error: %s", exc)

    # ── async variants ────────────────────────────────────────────────

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.log_success_event(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self.log_failure_event(kwargs, response_obj, start_time, end_time)


instance = SessionLogger()
