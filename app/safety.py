"""
Risk detection.

Design rule for the whole prototype: a 3B model does not get to decide whether
someone is at risk. This module runs on every inbound message BEFORE the model
sees it, uses no model, and its output is not advisory — a CRISIS result short-
circuits the session state machine and the generation call never happens.

Two layers:
  1. Lexical — fast, auditable, tuned for high recall. False positives are the
     acceptable direction of error here.
  2. (Phase 2, not built) A small fine-tuned classifier to catch what the
     lexical layer misses. It ADDS recall; it never overrides a lexical hit.

The lexical patterns below describe *intent and state*, deliberately not
methods. Nothing in this file, in the logs, or in the model's context should
carry method detail.

Every constant here is the clinical side's to own, not engineering's.
Dr. Dana's team signs off on the pattern list and the response copy before
any student-facing pilot. Ethics committee review (VC letter §8) covers this
file specifically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class Risk(IntEnum):
    NONE = 0
    WATCH = 1      # distress worth noting in the counsellor handoff, session continues
    ELEVATED = 2   # counsellor referral offered now, session continues in a careful mode
    CRISIS = 3     # session stops, crisis response only, human notified


@dataclass
class Assessment:
    level: Risk
    matched: list[str]
    reason: str

    @property
    def halts_session(self) -> bool:
        return self.level is Risk.CRISIS


# --- Layer 1 patterns -------------------------------------------------------
# Kept as plain readable regex so a psychologist can review them without
# reading Python. Add Hindi/Kannada equivalents before the multilingual phase.

_CRISIS = [
    r"\b(?:i|I)\s+(?:don'?t|do not|dont)\s+want\s+to\s+(?:live|be here|exist|wake up)\b",
    r"\bwant\s+to\s+(?:die|end\s+(?:it|everything|my\s+life))\b",
    r"\b(?:kill|killing|harm|hurt)\s+myself\b",
    r"\bend\s+my\s+life\b",
    r"\bbetter\s+off\s+(?:dead|without\s+me)\b",
    r"\bno\s+(?:point|reason)\s+(?:in\s+)?(?:living|going\s+on|being\s+alive)\b",
    r"\bsuicid(?:e|al)\b",
    r"\bi\s+(?:will|am\s+going\s+to|plan\s+to)\s+hurt\s+(?:someone|them|him|her)\b",
    r"\bi\s+(?:feel\s+)?unsafe\b.*\b(?:home|house|hostel|room)\b",
    r"\b(?:he|she|they|my\s+\w+)\s+(?:hits?|beats?|hurts?)\s+me\b",
    r"\bbeing\s+abused\b",
]

_ELEVATED = [
    r"\bpanic\s+attacks?\b",
    r"\bcan'?t\s+(?:stop|control)\s+crying\b",
    r"\bhaven'?t\s+(?:slept|eaten)\s+(?:in|for)\s+\d+\s+days?\b",
    r"\bnothing\s+matters\b",
    r"\bcompletely\s+(?:hopeless|worthless|numb)\b",
    r"\bcan'?t\s+(?:go\s+on|take\s+(?:it|this)\s+any\s*more)\b",
    r"\b(?:drinking|smoking|using)\s+(?:a\s+lot|every\s+day|to\s+cope)\b",
]

_WATCH = [
    r"\bhopeless\b", r"\bworthless\b", r"\bexhausted\b", r"\bburn(?:t|ed)\s+out\b",
    r"\bfalling\s+apart\b", r"\bcan'?t\s+cope\b", r"\balone\b", r"\bno\s+one\s+(?:cares|understands)\b",
]

# Contexts that commonly produce false positives. Present prototype only
# DOWNGRADES CRISIS -> ELEVATED on these, and never to NONE — a hedged
# disclosure is still a disclosure.
_SOFTENERS = [
    r"\b(?:movie|film|book|novel|game|character|assignment|essay|psychology\s+class|case\s+study)\b",
    r"\b(?:my\s+friend|someone\s+i\s+know|a\s+classmate)\b",   # still routes to a human, just differently
    r"\bused\s+to\s+(?:feel|think)\b",
]

_C = [re.compile(p, re.I) for p in _CRISIS]
_E = [re.compile(p, re.I) for p in _ELEVATED]
_W = [re.compile(p, re.I) for p in _WATCH]
_S = [re.compile(p, re.I) for p in _SOFTENERS]


def assess(text: str) -> Assessment:
    hits_c = [p.pattern for p in _C if p.search(text)]
    if hits_c:
        softened = any(p.search(text) for p in _S)
        if softened:
            return Assessment(Risk.ELEVATED, hits_c,
                              "crisis language in a context that may be third-party or hypothetical")
        return Assessment(Risk.CRISIS, hits_c, "explicit risk language")

    hits_e = [p.pattern for p in _E if p.search(text)]
    if hits_e:
        return Assessment(Risk.ELEVATED, hits_e, "acute distress language")

    hits_w = [p.pattern for p in _W if p.search(text)]
    if hits_w:
        return Assessment(Risk.WATCH, hits_w, "distress language")

    return Assessment(Risk.NONE, [], "")


# --- Crisis response --------------------------------------------------------
# Fixed copy. The model does not write this. Verify every number with the
# counselling department before the pilot — an out-of-date helpline in a
# crisis screen is worse than none.

CRISIS_RESOURCES = {
    "national": {
        "name": "Tele-MANAS (Govt. of India, 24x7, 20 languages)",
        "numbers": ["14416", "1-800-891-4416"],
    },
    "campus": {
        "name": "Presidency University Counselling Department",
        "numbers": ["<< fill in before pilot >>"],
        "hours": "<< fill in >>",
    },
}

CRISIS_MESSAGE = (
    "I want to stop and stay with what you just said, because it matters more than "
    "anything else we were doing.\n\n"
    "I'm not the right kind of help for this, and I don't want to pretend otherwise. "
    "Please talk to someone who is — right now if you can:\n\n"
    "• Tele-MANAS, free and 24x7: **14416** or **1-800-891-4416**\n"
    "• The university counselling department: {campus}\n"
    "• Someone you trust who is physically near you — a friend, a warden, family\n\n"
    "If you're in immediate danger, call **112**.\n\n"
    "I'm keeping this conversation open. You don't have to say anything more to me."
)


def crisis_payload() -> dict:
    return {
        "message": CRISIS_MESSAGE.format(
            campus=", ".join(CRISIS_RESOURCES["campus"]["numbers"])
        ),
        "resources": CRISIS_RESOURCES,
        "notify_counsellor": True,   # Phase 2: actually fires the on-call alert
        "session_halted": True,
    }
