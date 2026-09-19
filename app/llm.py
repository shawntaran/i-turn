"""
Language-model access for the application.

There is no model in this process. Every call goes through app/ai_client.py to
an AI server at AI_BASE_URL, which may be running on this machine, in a Google
Colab notebook, or anywhere else that speaks the same HTTP contract. Nothing
here knows or cares which.

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
import re
from dataclasses import dataclass

from .ai_client import AIClient, AIError, from_env

__all__ = ["AIError", "GenConfig", "get_client", "set_client", "reply", "extract", "extract_likert"]

_client: AIClient | None = None


def get_client() -> AIClient:
    """The process-wide client, built from the environment on first use."""
    global _client
    if _client is None:
        _client = from_env()
    return _client


def set_client(client: AIClient | None) -> None:
    """Swap the client (tests, or a future settings screen). None resets it."""
    global _client
    _client = client


@dataclass
class GenConfig:
    temperature: float = 0.6
    top_p: float = 0.9
    max_tokens: int = 220        # one conversational turn, not an essay
    repeat_penalty: float = 1.1


def _chat(system: str, messages: list[dict], cfg: GenConfig | None = None,
          json_mode: bool = False) -> str:
    cfg = cfg or GenConfig()
    return get_client().generate(
        messages=messages,
        system_prompt=system,
        temperature=0.0 if json_mode else cfg.temperature,
        top_p=cfg.top_p,
        max_tokens=128 if json_mode else cfg.max_tokens,
        repeat_penalty=cfg.repeat_penalty,
        json_mode=json_mode,
    ).text


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def reply(system: str, history: list[dict], cfg: GenConfig | None = None) -> str:
    """One conversational turn. Post-processed to strip small-model tics."""
    return _clean(_chat(system, history, cfg))


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
        raw = _chat(system, [{"role": "user", "content": user}],
                    GenConfig(temperature=0.0), json_mode=True)
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

    try:
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
    except AIError:
        # The AI server is unreachable. The questionnaire itself is
        # deterministic, so it carries on: None means "show the buttons".
        return None
    val = result.get("rating")
    return val if isinstance(val, int) and 0 <= val <= 3 else None
