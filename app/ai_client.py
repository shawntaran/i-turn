"""
HTTP client for the I-Turn AI server.

This is the only way the application talks to a language model. There is no
model, tokenizer, torch or CUDA anywhere in this package; the model lives behind
a URL (AI_BASE_URL) and the URL can point at a local process, a Colab notebook
behind a tunnel, or any other server that speaks the same contract.

The contract (see ai_server/server.py for the reference implementation):

    POST /v1/generate   ->  {"text", "model", "finish_reason", "usage"}
    GET  /health        ->  {"status": "ok" | "loading" | "error", "model", ...}

Everything that can go wrong on the way — server down, bad URL, timeout, model
still loading, GPU out of memory, garbage in the response — comes out of here as
one exception type, AIError, carrying a message that is safe to show a student.
The underlying detail is logged, never returned.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("iturn.ai")

DEFAULT_BASE_URL = "http://localhost:8001"
DEFAULT_TIMEOUT = 120.0
CONNECT_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

_USER_MESSAGES = {
    "unavailable": (
        "AI service unavailable. Check that the AI server (for example the Google "
        "Colab notebook) is running and that AI_BASE_URL is correct."
    ),
    "bad_url": (
        "AI_BASE_URL is not a valid URL. It should look like "
        "https://xxxxx.trycloudflare.com or http://localhost:8001."
    ),
    "timeout": "The AI service took too long to respond. Try again in a moment.",
    "interrupted": "The connection to the AI service was interrupted. Try again.",
    "unauthorized": (
        "The AI service rejected the request. Check that AI_API_KEY matches the "
        "key shown by the AI server."
    ),
    "model_loading": "The AI model is still loading. Wait a minute and try again.",
    "model_error": (
        "The AI model failed to load on the AI server. Check the server's log for the reason."
    ),
    "out_of_memory": (
        "The AI server ran out of GPU memory. Restart it, or choose a smaller model."
    ),
    "invalid_response": "The AI service returned a response that could not be used. Try again.",
    "server_error": "The AI service reported an error. Try again.",
    "bad_request": "The AI service could not accept the request. This is a bug in I-Turn.",
}


class AIError(Exception):
    """A failure talking to the AI server.

    `message` is safe to show to a student. `detail` is for the log only and
    may contain URLs, status codes or fragments of a response body.
    """

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.message = _USER_MESSAGES.get(code, _USER_MESSAGES["server_error"])
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass
class GenerateResult:
    text: str
    model: str = ""
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AIClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        model: str = "",
    ):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.model = model.strip()
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(CONNECT_TIMEOUT, timeout))
        )

    # -- public ---------------------------------------------------------------

    def generate(
        self,
        prompt: str | None = None,
        *,
        messages: list[dict] | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        top_p: float | None = None,
        max_tokens: int = 1024,
        repeat_penalty: float | None = None,
        json_mode: bool = False,
    ) -> GenerateResult:
        """Send either a single `prompt` or a `messages` list (chat history)."""
        payload: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "json_mode": json_mode,
        }
        if prompt is not None:
            payload["prompt"] = prompt
        if messages is not None:
            payload["messages"] = messages
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if top_p is not None:
            payload["top_p"] = top_p
        if repeat_penalty is not None:
            payload["repeat_penalty"] = repeat_penalty
        if self.model:
            payload["model"] = self.model

        r = self._request("POST", "/v1/generate", json=payload)
        return self._parse_generate(r)

    def health(self) -> dict[str, Any]:
        """
        Ask the server how it is. Returns its JSON body — status is "ok",
        "loading" or "error" — without raising for a server that is reachable
        but not ready. Raises AIError only when the server can't be reached or
        isn't an I-Turn AI server at all.
        """
        r = self._request("GET", "/health", accept_unready=True)
        try:
            body = r.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or body.get("status") not in {"ok", "loading", "error"}:
            raise AIError("invalid_response", f"/health returned {r.text[:200]!r}")
        return body

    # -- internals ------------------------------------------------------------

    def _request(self, method: str, path: str, *, accept_unready: bool = False,
                 **kwargs: Any) -> httpx.Response:
        if not self.base_url.startswith(("http://", "https://")):
            raise AIError("bad_url", f"AI_BASE_URL={self.base_url!r}")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.base_url}{path}"
        try:
            r = self._http.request(method, url, headers=headers, **kwargs)
        except httpx.ConnectTimeout as e:
            raise AIError("unavailable", f"connect timeout to {url}") from e
        except httpx.TimeoutException as e:
            raise AIError("timeout", f"{type(e).__name__} after {self.timeout}s on {url}") from e
        except (httpx.UnsupportedProtocol, httpx.InvalidURL) as e:
            raise AIError("bad_url", f"{e} ({self.base_url!r})") from e
        except httpx.ConnectError as e:
            raise AIError("unavailable", f"{type(e).__name__}: {e} ({url})") from e
        except httpx.TransportError as e:
            # Connection dropped mid-request, malformed HTTP, TLS failure, ...
            raise AIError("interrupted", f"{type(e).__name__}: {e} ({url})") from e

        if r.is_success or (accept_unready and r.status_code == 503):
            return r
        raise self._http_error(r)

    @staticmethod
    def _http_error(r: httpx.Response) -> AIError:
        code = None
        try:
            body = r.json()
            code = body["error"]["code"] if isinstance(body.get("error"), dict) else None
        except (ValueError, KeyError, AttributeError):
            pass
        detail = f"HTTP {r.status_code}: {r.text[:200]!r}"

        if r.status_code in (401, 403):
            return AIError("unauthorized", detail)
        if code in ("model_loading", "model_error", "out_of_memory"):
            return AIError(code, detail)
        if r.status_code == 504:
            return AIError("timeout", detail)
        if r.status_code in (404, 405, 502, 503) or r.status_code >= 520:
            # Wrong URL, or a tunnel/proxy with nothing behind it (Cloudflare
            # answers 530 when the Colab side has gone away).
            return AIError("unavailable", detail)
        if r.status_code >= 500:
            return AIError("server_error", detail)
        return AIError("bad_request", detail)

    @staticmethod
    def _parse_generate(r: httpx.Response) -> GenerateResult:
        try:
            body = r.json()
        except ValueError as e:
            raise AIError("invalid_response", f"not JSON: {r.text[:200]!r}") from e
        if not isinstance(body, dict):
            raise AIError("invalid_response", f"expected an object, got {type(body).__name__}")
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise AIError("invalid_response", f"missing or empty 'text' in {str(body)[:200]!r}")
        usage = body.get("usage")
        return GenerateResult(
            text=text,
            model=str(body.get("model") or ""),
            finish_reason=str(body.get("finish_reason") or "stop"),
            usage=usage if isinstance(usage, dict) else {},
        )

    def close(self) -> None:
        self._http.close()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def from_env() -> AIClient:
    """Build the client from AI_BASE_URL / AI_API_KEY / AI_TIMEOUT / AI_MODEL.

    A `.env` file at the repository root is read if present; real environment
    variables win over it.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    except ImportError:  # python-dotenv is a convenience, not a requirement
        pass

    try:
        timeout = float(os.environ.get("AI_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        log.warning("AI_TIMEOUT is not a number; using %ss", DEFAULT_TIMEOUT)
        timeout = DEFAULT_TIMEOUT
    return AIClient(
        base_url=os.environ.get("AI_BASE_URL") or DEFAULT_BASE_URL,
        api_key=os.environ.get("AI_API_KEY", ""),
        timeout=timeout,
        model=os.environ.get("AI_MODEL", ""),
    )
