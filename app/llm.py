"""
Model backend.

Two interchangeable backends, same interface:
  - "ollama"       : local llama.cpp server. Default. Easiest on the RTX 5050.
  - "transformers" : HF, for Colab or if you want LoRA later.
  - "stub"         : no model at all, deterministic canned text. Used by tests
                     and by anyone who wants to work on the state machine or UI
                     without a GPU.

The model is asked to do exactly two things, both narrow:
  reply()   — write one empathic conversational turn
  extract() — turn free text into a small JSON object

It is never asked to score, to decide severity, to decide escalation, or to
choose what question comes next. That is all in session.py and the instrument
modules, deterministically. This is not a stylistic preference — it is the only
way a 3B model is defensible in a mental-health setting.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

Backend = Literal["ollama", "transformers", "stub"]

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("ITURN_MODEL", "qwen2.5:3b-instruct-q4_K_M")
BACKEND: Backend = os.environ.get("ITURN_BACKEND", "ollama")  # type: ignore[assignment]


@dataclass
class GenConfig:
    temperature: float = 0.6
    top_p: float = 0.9
    max_tokens: int = 220        # one conversational turn, not an essay
    repeat_penalty: float = 1.1


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def _ollama_chat(messages: list[dict], cfg: GenConfig, json_mode: bool = False) -> str:
    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.0 if json_mode else cfg.temperature,
            "top_p": cfg.top_p,
            "num_predict": 128 if json_mode else cfg.max_tokens,
            "repeat_penalty": cfg.repeat_penalty,
        },
    }
    if json_mode:
        payload["format"] = "json"
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120.0)
    r.raise_for_status()
    return r.json()["message"]["content"]


# ---------------------------------------------------------------------------
# transformers (Colab / when you want the raw weights)
# ---------------------------------------------------------------------------

_hf: dict[str, Any] = {}


def _load_hf() -> None:
    if _hf:
        return
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    name = os.environ.get("ITURN_HF_MODEL", "Qwen/Qwen2.5-3B-Instruct")
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForCausalLM.from_pretrained(
        name,
        dtype=torch.bfloat16,          # 5050 is Blackwell; bf16 is fine
        device_map="auto",
    )
    _hf["tok"], _hf["model"], _hf["torch"] = tok, model, torch


def _hf_chat(messages: list[dict], cfg: GenConfig, json_mode: bool = False) -> str:
    _load_hf()
    tok, model, torch = _hf["tok"], _hf["model"], _hf["torch"]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok([text], return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=128 if json_mode else cfg.max_tokens,
            do_sample=not json_mode,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            repetition_penalty=cfg.repeat_penalty,
            pad_token_id=tok.eos_token_id,
        )
    return tok.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)


# ---------------------------------------------------------------------------
# stub
# ---------------------------------------------------------------------------

def _stub_chat(messages: list[dict], cfg: GenConfig, json_mode: bool = False) -> str:
    if json_mode:
        return "{}"
    return "[stub backend] I hear you. Tell me a bit more about how that's been going."


_BACKENDS = {"ollama": _ollama_chat, "transformers": _hf_chat, "stub": _stub_chat}


def _chat(messages: list[dict], cfg: GenConfig | None = None, json_mode: bool = False) -> str:
    return _BACKENDS[BACKEND](messages, cfg or GenConfig(), json_mode)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def reply(system: str, history: list[dict], cfg: GenConfig | None = None) -> str:
    """One conversational turn. Post-processed to strip small-model tics."""
    raw = _chat([{"role": "system", "content": system}, *history], cfg)
    return _clean(raw)


_TICS = (
    re.compile(r"^\s*(?:Assistant|AI|Counsellor|I-Turn)\s*:\s*", re.I),
    re.compile(r"\*[^*]{0,60}(?:nods|smiles|pauses|leans)[^*]{0,60}\*"),  # roleplay asterisks
    re.compile(r"^\s*(?:As an AI[^.]*\.|I'm just an AI[^.]*\.)\s*", re.I),
)


def _clean(text: str) -> str:
    out = text.strip()
    for pat in _TICS:
        out = pat.sub("", out)
    # 3B models love to stack three questions in a turn. Keep the first.
    parts = re.split(r"(?<=\?)\s+", out)
    if len(parts) > 2 and sum(p.rstrip().endswith("?") for p in parts) > 1:
        kept, seen_q = [], False
        for p in parts:
            if p.rstrip().endswith("?"):
                if seen_q:
                    break
                seen_q = True
            kept.append(p)
        out = " ".join(kept)
    return out.strip()


def extract(instruction: str, text: str, schema_hint: str, retries: int = 2) -> dict:
    """
    Constrained extraction. Returns {} rather than guessing — an empty result
    makes the state machine ask the question plainly, which is always a safe
    fallback. Never let this function invent a value.
    """
    system = (
        "You convert a person's message into JSON. Output JSON only, no prose, "
        "no markdown fences. If the message does not clearly contain the value, "
        "omit the key entirely. Never guess.\n\n"
        f"Schema: {schema_hint}"
    )
    user = f"{instruction}\n\nMessage: \"\"\"{text}\"\"\""
    for _ in range(retries + 1):
        raw = _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            GenConfig(temperature=0.0),
            json_mode=True,
        )
        parsed = _parse_json(raw)
        if parsed is not None:
            return parsed
    return {}


def _parse_json(raw: str) -> dict | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)   # model wrapped it in chatter
        if m:
            try:
                val = json.loads(m.group(0))
                return val if isinstance(val, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def extract_likert(item_text: str, user_text: str) -> int | None:
    """
    Map a free-text reply to a DASS-21 item onto 0-3.

    Returns None whenever it isn't obvious, and None means the UI shows the
    four buttons and the student picks. That is the desired behaviour, not a
    failure — an inferred rating that the student never confirmed is not a
    valid DASS response.
    """
    # Cheap path first: they just typed a number or tapped a button.
    m = re.fullmatch(r"\s*([0-3])\s*", user_text)
    if m:
        return int(m.group(1))

    result = extract(
        instruction=(
            "The person is responding to this statement about the past week: "
            f"\"{item_text}\". On a 0-3 scale where "
            "0 = did not apply to me at all, "
            "1 = applied to some degree or some of the time, "
            "2 = applied to a considerable degree or a good part of the time, "
            "3 = applied very much or most of the time — "
            "what rating did they express? Omit 'rating' unless it is unambiguous."
        ),
        text=user_text,
        schema_hint='{"rating": 0|1|2|3}',
    )
    val = result.get("rating")
    return val if isinstance(val, int) and 0 <= val <= 3 else None
