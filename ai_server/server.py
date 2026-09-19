"""
I-Turn AI server — the only place in the project where a model is loaded.

The application (app/) never imports torch or transformers. It sends HTTP
requests to this server, or to anything else that implements the same contract.
This file is the reference implementation of that contract. It is deliberately a
single file so the Colab notebook can embed it verbatim; collab/build_notebook.py
keeps the two in sync.

CONTRACT (version 1)
--------------------
POST /v1/generate
    {
      "prompt":         "..."                     # a single user message, OR
      "messages":       [{"role": "user|assistant|system", "content": "..."}],
      "system_prompt":  "..."                     # optional
      "temperature":    0.7,   "top_p": 0.9,   "max_tokens": 1024,
      "repeat_penalty": 1.0,   "json_mode": false,
      "model":          "..."                     # advisory; see below
    }
    ->
    {
      "text": "...", "model": "...", "finish_reason": "stop" | "length",
      "usage": {"input_tokens": 0, "output_tokens": 0}
    }

GET /health
    {"status": "ok" | "loading" | "error", "model": "...", "engine": "...", ...}
    200 when ready, 503 otherwise.

Errors are always {"error": {"code": "...", "message": "..."}} with codes:
    unauthorized, model_loading, model_error, out_of_memory, generation_failed

The model that answers is whichever one this server loaded. A `model` field in
the request is advisory: it is logged if it differs, and the response always
says which model actually produced the text. Whatever the underlying model
emits, the response has exactly this shape — the application never needs to know
which model it is talking to.

ENGINES
-------
The engine is how this server runs a model. It is chosen by AI_ENGINE:
    transformers  Hugging Face model on this machine's GPU (Colab). Default.
    ollama        Forwards to a local Ollama instance.
    stub          No model. Canned text. For UI/tests on a laptop with no GPU.

CONFIGURATION (environment)
---------------------------
    AI_ENGINE     transformers | ollama | stub          (default: transformers)
    MODEL_NAME    HF repo id, or Ollama tag              (default: Qwen/Qwen2.5-3B-Instruct)
    AI_API_KEY    if set, every request must send "Authorization: Bearer <key>"
    HOST / PORT   where to listen                        (default: 127.0.0.1:8001)
    LOAD_IN_4BIT  "1" to load the transformers model in 4-bit (needs bitsandbytes)
    OLLAMA_URL    (default: http://127.0.0.1:11434)

Run:  python -m ai_server.server          (from the repository root)
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger("ai_server")

CONTRACT_VERSION = "1"
DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class GenerateRequest(BaseModel):
    prompt: str | None = Field(default=None, min_length=1)
    messages: list[Message] | None = Field(default=None, min_length=1, max_length=200)
    system_prompt: str | None = None
    model: str | None = None
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: float = Field(0.9, gt=0.0, le=1.0)
    max_tokens: int = Field(1024, ge=1, le=4096)
    repeat_penalty: float = Field(1.0, ge=1.0, le=2.0)   # 1.0 = off
    json_mode: bool = False

    @model_validator(mode="after")
    def _one_input(self) -> "GenerateRequest":
        if (self.prompt is None) == (self.messages is None):
            raise ValueError("send exactly one of 'prompt' or 'messages'")
        return self

    def chat_messages(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if self.system_prompt:
            out.append({"role": "system", "content": self.system_prompt})
        if self.messages is not None:
            out.extend(m.model_dump() for m in self.messages)
        else:
            out.append({"role": "user", "content": self.prompt or ""})
        return out


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class GenerateResponse(BaseModel):
    text: str
    model: str
    finish_reason: Literal["stop", "length"] = "stop"
    usage: Usage = Usage()


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------

@dataclass
class Params:
    temperature: float
    top_p: float
    max_tokens: int
    repeat_penalty: float
    json_mode: bool


@dataclass
class Completion:
    text: str
    finish_reason: str = "stop"
    input_tokens: int = 0
    output_tokens: int = 0


class EngineError(Exception):
    """A failure inside an engine, already classified with a contract code."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")


class Engine:
    name = "base"

    def __init__(self, model: str):
        self.model = model

    def load(self) -> None:
        """Blocking; may take minutes. Raise EngineError('model_error', ...) on failure."""

    def generate(self, messages: list[dict[str, str]], p: Params) -> Completion:
        raise NotImplementedError


class StubEngine(Engine):
    """No model at all. Lets the whole application run on a laptop with nothing
    installed but the app's own dependencies."""

    name = "stub"

    def generate(self, messages: list[dict[str, str]], p: Params) -> Completion:
        text = ("{}" if p.json_mode else
                "[stub] I hear you. Tell me a bit more about how that's been going.")
        return Completion(text=text, output_tokens=len(text.split()),
                          input_tokens=sum(len(m["content"].split()) for m in messages))


class OllamaEngine(Engine):
    """Forwards to a local Ollama. Keeps a local-GPU workflow that already uses
    Ollama working behind the same contract."""

    name = "ollama"

    def __init__(self, model: str, url: str = "http://127.0.0.1:11434"):
        super().__init__(model)
        self.url = url.rstrip("/")
        # One pooled client: a fresh connection per call costs ~0.7s on Windows
        # (~2.7s via "localhost"), which dwarfs generation time on a small model.
        self._http = httpx.Client(timeout=300, limits=httpx.Limits(keepalive_expiry=60.0))

    def load(self) -> None:
        try:
            tags = self._http.get(f"{self.url}/api/tags", timeout=10).json()
        except (httpx.HTTPError, ValueError) as e:
            raise EngineError("model_error", f"Ollama not reachable at {self.url}: {e}") from e
        names = {m.get("name") for m in tags.get("models", [])}
        if self.model not in names:
            raise EngineError("model_error",
                              f"Ollama has no model {self.model!r}. Run: ollama pull {self.model}")

    def generate(self, messages: list[dict[str, str]], p: Params) -> Completion:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": p.temperature, "top_p": p.top_p,
                        "num_predict": p.max_tokens, "repeat_penalty": p.repeat_penalty},
        }
        if p.json_mode:
            payload["format"] = "json"
        try:
            r = self._http.post(f"{self.url}/api/chat", json=payload)
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise EngineError("generation_failed", f"Ollama request failed: {e}") from e
        return Completion(
            text=body["message"]["content"],
            finish_reason="length" if body.get("done_reason") == "length" else "stop",
            input_tokens=int(body.get("prompt_eval_count", 0)),
            output_tokens=int(body.get("eval_count", 0)),
        )


class TransformersEngine(Engine):
    """Any Hugging Face causal LM that ships a chat template."""

    name = "transformers"

    def __init__(self, model: str, load_in_4bit: bool = False):
        super().__init__(model)
        self.load_in_4bit = load_in_4bit
        self._tok = self._model = self._torch = None
        self._eos: set[int] = set()

    def load(self) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            if not torch.cuda.is_available():
                log.warning("No GPU visible to torch. Generation will be very slow. "
                            "In Colab: Runtime -> Change runtime type -> GPU.")
            # T4 (Colab's free GPU) has no fast bfloat16; newer GPUs prefer it.
            dtype = (torch.bfloat16
                     if torch.cuda.is_available() and torch.cuda.is_bf16_supported()
                     else torch.float16 if torch.cuda.is_available() else torch.float32)
            kwargs: dict[str, Any] = {"torch_dtype": dtype, "device_map": "auto"}
            if self.load_in_4bit:
                from transformers import BitsAndBytesConfig
                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_compute_dtype=dtype)

            log.info("Loading %s (dtype=%s, 4bit=%s)", self.model, dtype, self.load_in_4bit)
            self._tok = AutoTokenizer.from_pretrained(self.model)
            self._model = AutoModelForCausalLM.from_pretrained(self.model, **kwargs)
            self._model.eval()
            self._torch = torch

            eos = self._model.generation_config.eos_token_id
            self._eos = set(eos if isinstance(eos, list) else [eos]) if eos is not None else set()
            if self._tok.eos_token_id is not None:
                self._eos.add(self._tok.eos_token_id)
        except Exception as e:  # noqa: BLE001 — any failure here means "no model"
            oom = "out of memory" in str(e).lower()
            hint = " (GPU out of memory: pick a smaller model or set LOAD_IN_4BIT)" if oom else ""
            raise EngineError("model_error", f"{type(e).__name__}: {e}{hint}") from e

    def _render(self, messages: list[dict[str, str]]) -> str:
        tok = self._tok
        try:
            return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:  # noqa: BLE001
            # Some templates (Gemma, some Mistral) reject a system role. Fold it
            # into the first user turn instead of failing.
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            rest = [dict(m) for m in messages if m["role"] != "system"]
            if system and rest and rest[0]["role"] == "user":
                rest[0]["content"] = f"{system}\n\n{rest[0]['content']}"
            return tok.apply_chat_template(rest, tokenize=False, add_generation_prompt=True)

    def generate(self, messages: list[dict[str, str]], p: Params) -> Completion:
        torch, tok, model = self._torch, self._tok, self._model
        text = self._render(messages)
        # The template already contains any BOS token; don't add a second one.
        inputs = tok(text, return_tensors="pt", add_special_tokens=False).to(model.device)
        gen: dict[str, Any] = {
            "max_new_tokens": p.max_tokens,
            "repetition_penalty": p.repeat_penalty,
            "pad_token_id": tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id,
        }
        if p.temperature > 0:
            gen.update(do_sample=True, temperature=p.temperature, top_p=p.top_p)
        else:
            gen.update(do_sample=False)
        try:
            with torch.no_grad():
                out = model.generate(**inputs, **gen)
        except torch.cuda.OutOfMemoryError as e:
            torch.cuda.empty_cache()
            raise EngineError("out_of_memory", "GPU ran out of memory during generation") from e

        n_in = inputs["input_ids"].shape[1]
        new = out[0][n_in:]
        hit_eos = len(new) > 0 and int(new[-1]) in self._eos
        return Completion(
            text=tok.decode(new, skip_special_tokens=True),
            finish_reason="stop" if hit_eos or len(new) < p.max_tokens else "length",
            input_tokens=int(n_in),
            output_tokens=int(len(new)),
        )


def build_engine(name: str, model: str) -> Engine:
    if name == "stub":
        return StubEngine(model or "stub")
    if name == "ollama":
        return OllamaEngine(model, os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    if name == "transformers":
        return TransformersEngine(model, load_in_4bit=os.environ.get("LOAD_IN_4BIT") == "1")
    raise ValueError(f"unknown AI_ENGINE {name!r} (use transformers, ollama or stub)")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class ServerError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def create_app(engine: Engine, api_key: str = "") -> FastAPI:
    state: dict[str, str] = {"status": "loading", "detail": ""}
    gpu_lock = threading.Lock()      # one generation at a time on one GPU

    def load_in_background() -> None:
        try:
            engine.load()
            state["status"] = "ok"
            log.info("Model ready: %s (%s)", engine.model, engine.name)
        except EngineError as e:
            state.update(status="error", detail=e.message)
            log.error("Model failed to load: %s", e.message)
        except Exception as e:  # noqa: BLE001
            state.update(status="error", detail=f"{type(e).__name__}: {e}")
            log.exception("Model failed to load")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Serve /health immediately and load in the background, so a caller can
        # tell "still loading" from "nothing there".
        threading.Thread(target=load_in_background, daemon=True).start()
        yield

    app = FastAPI(title="I-Turn AI server", lifespan=lifespan)

    def require_key(authorization: str | None = Header(default=None)) -> None:
        if not api_key:
            return
        if not authorization or not hmac.compare_digest(authorization, f"Bearer {api_key}"):
            raise ServerError(401, "unauthorized", "missing or invalid API key")

    @app.exception_handler(ServerError)
    async def _server_error(_: Request, exc: ServerError) -> JSONResponse:
        return JSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": exc.message}})

    @app.get("/health")
    def health(_: None = Depends(require_key)) -> JSONResponse:
        body: dict[str, Any] = {"status": state["status"], "model": engine.model,
                                "engine": engine.name, "contract": CONTRACT_VERSION}
        if state["detail"]:
            body["detail"] = state["detail"]
        return JSONResponse(status_code=200 if state["status"] == "ok" else 503, content=body)

    @app.post("/v1/generate", response_model=GenerateResponse)
    def generate(req: GenerateRequest, _: None = Depends(require_key)) -> GenerateResponse:
        if state["status"] == "loading":
            raise ServerError(503, "model_loading", "the model is still loading")
        if state["status"] == "error":
            raise ServerError(503, "model_error", state["detail"] or "the model failed to load")
        if req.model and req.model != engine.model:
            log.warning("Request asked for model %r; serving %r", req.model, engine.model)

        params = Params(req.temperature, req.top_p, req.max_tokens,
                        req.repeat_penalty, req.json_mode)
        try:
            with gpu_lock:
                c = engine.generate(req.chat_messages(), params)
        except EngineError as e:
            status = 503 if e.code == "out_of_memory" else 500
            raise ServerError(status, e.code, e.message) from e
        except Exception as e:  # noqa: BLE001
            log.exception("Generation failed")
            raise ServerError(500, "generation_failed", f"{type(e).__name__}") from e

        return GenerateResponse(
            text=(c.text or "").strip(),
            model=engine.model,
            finish_reason="length" if c.finish_reason == "length" else "stop",
            usage=Usage(input_tokens=c.input_tokens, output_tokens=c.output_tokens),
        )

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = build_engine(os.environ.get("AI_ENGINE", "transformers"),
                          os.environ.get("MODEL_NAME", DEFAULT_MODEL))
    app = create_app(engine, api_key=os.environ.get("AI_API_KEY", ""))
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8001")), log_level="info")


if __name__ == "__main__":
    main()
