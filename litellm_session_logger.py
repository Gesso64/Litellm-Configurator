"""LiteLLM proxy post-call hook: append one JSONL line per request.

Writes to ~/.claude/litellm-session-log.jsonl. Each line:
  timestamp_utc, request_id, alias_requested, upstream_model,
  prompt_tokens, completion_tokens, latency_ms, status, error, session_id,
  user, ip

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
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning("session_logger: cannot create log dir: %s", exc)

    def _write(self, entry: dict) -> None:
        try:
            line = json.dumps(entry, default=str, ensure_ascii=False)
            with self._lock:
                with LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as exc:
            log.warning("session_logger: write failed: %s", exc)

    def _build_entry(self, kwargs: dict, response_obj, start_time, end_time, status: str, error: str | None) -> dict:
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
        }

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
            self._write(self._build_entry(kwargs, response_obj, start_time, end_time, "ok", None))
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
