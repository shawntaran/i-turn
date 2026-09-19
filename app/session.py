"""
Session orchestrator.

The shape of a session is open conversation. There is no wizard, no fixed
question order, no required path. The instruments are interludes that the
conversation can offer, the student can decline, and the session survives
either way.

Control flow lives here, in Python. The model contributes language only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import db, llm, prompts, safety
from .instruments import dass21, lifestyle


class Phase(str, Enum):
    OPEN = "open"                 # free conversation — the default and the norm
    OFFERING = "offering"         # a questionnaire has been offered this turn
    INSTRUMENT = "instrument"     # part-way through DASS-21
    POST = "post"                 # just showed results
    HALTED = "halted"             # crisis — model is out of the loop


class Mode(str, Enum):
    STORY = "story"
    INCOGNITO = "incognito"


# When to offer the questionnaire. Not a rule the model can bend.
MIN_TURNS_BEFORE_OFFER = 6
DASS_BLOCK_SIZE = 3


@dataclass
class Session:
    pseudonym: str
    mode: Mode = Mode.INCOGNITO
    language: str = "English"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    history: list[dict] = field(default_factory=list)
    phase: Phase = Phase.OPEN

    dass: dict[int, int] = field(default_factory=dict)
    dass_offered: bool = False
    dass_declined: bool = False
    pending_item: int | None = None

    profile: lifestyle.LifestyleProfile = field(default_factory=lifestyle.LifestyleProfile)
    peak_risk: safety.Risk = safety.Risk.NONE
    risk_notes: list[str] = field(default_factory=list)

    conn: Any = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self.mode is Mode.STORY:
            self.conn = db.connect()
            db.grant_consent(self.conn, self.pseudonym, self.session_id, "store_conversation")
            for role, content in db.prior_turns(self.conn, self.pseudonym, self.session_id):
                self.history.append({"role": role, "content": content})
        else:
            # Risk events are logged even in Incognito. The student is told this
            # before the session starts — see PRIVACY_NOTICE in main.py.
            self.conn = db.connect()

    # -- the one entry point ------------------------------------------------

    def turn(self, text: str) -> dict:
        # 1. Safety runs first, on raw input, with no model involvement.
        risk = safety.assess(text)
        if risk.level > self.peak_risk:
            self.peak_risk = risk.level
        if risk.level >= safety.Risk.ELEVATED:
            self.risk_notes.append(risk.reason)
            db.log_risk(self.conn, self.pseudonym, self.session_id, int(risk.level), risk.reason)

        if risk.halts_session:
            self.phase = Phase.HALTED
            self._record("user", text)
            payload = safety.crisis_payload()
            self._record("assistant", payload["message"])
            return {"phase": self.phase.value, **payload}

        if self.phase is Phase.HALTED:
            # Student kept talking after a crisis response. Stay quiet and human-
            # shaped; do not resume normal chat, do not run the model.
            return {
                "phase": "halted",
                "message": "I'm still here. Have you been able to reach someone?",
                "session_halted": True,
            }

        self._record("user", text)

        # 2. Mid-instrument? Try to read a rating; fall back to buttons.
        if self.phase is Phase.INSTRUMENT and self.pending_item is not None:
            return self._instrument_turn(text)

        # 3. Open conversation. Everything that can call the model is inside
        #    this block: if the AI server fails, the turn is undone so the
        #    student can simply send it again.
        try:
            # Harvest lifestyle slots quietly, from what they volunteered.
            self._harvest_lifestyle(text)

            # Decide whether this is a moment to offer the questionnaire.
            offering = self._should_offer()
            phase_for_prompt = self.phase.value
            if offering:
                phase_for_prompt = "offer"
            elif self.peak_risk >= safety.Risk.ELEVATED:
                phase_for_prompt = "elevated"

            msg = llm.reply(
                prompts.system_prompt(self.language, phase_for_prompt),
                self.history[-12:],
            )
        except llm.AIError:
            self._undo_user_turn()
            raise

        # Only now is the offer real: the student is about to see it.
        if offering:
            self.dass_offered = True
            self.phase = Phase.OFFERING
        self._record("assistant", msg)

        out: dict = {"phase": self.phase.value, "message": msg}
        if phase_for_prompt == "offer":
            out["offer"] = {
                "instrument": "dass21",
                "prompt": dass21.CONSENT_PROMPT,
                "actions": ["Sure", "Not now"],
            }
        return out

    # -- instrument handling -------------------------------------------------

    def accept_instrument(self) -> dict:
        self.phase = Phase.INSTRUMENT
        return self._serve_next()

    def decline_instrument(self) -> dict:
        self.dass_declined = True
        self.phase = Phase.OPEN
        return {"phase": "open", "message": "No problem. What were you saying?"}

    def answer_item(self, item: int, value: int) -> dict:
        """Explicit button press. This is the only path that produces a
        confirmed DASS response."""
        if item not in dass21.BY_NUMBER or value not in (0, 1, 2, 3):
            raise ValueError("invalid DASS-21 response")
        self.dass[item] = value
        db.save_response(self.conn, self.pseudonym, self.session_id, "dass21", item, value, True)
        return self._serve_next()

    def _instrument_turn(self, text: str) -> dict:
        item = dass21.BY_NUMBER[self.pending_item]  # type: ignore[index]
        guess = llm.extract_likert(item.text, text)
        if guess is None:
            # Ambiguous. Ask plainly with the anchors — never infer a DASS value.
            return {
                "phase": "instrument",
                "message": "Sorry, let me be precise about this one.",
                "item": _item_payload(item),
                "needs_explicit": True,
            }
        # Got a reading, but it is a *suggestion* until they confirm it.
        return {
            "phase": "instrument",
            "message": f"Sounds like about {guess} — {dass21.ANCHORS[guess].lower()}. That right?",
            "item": _item_payload(item),
            "suggested": guess,
            "needs_confirmation": True,
        }

    def _serve_next(self) -> dict:
        batch = dass21.next_items(self.dass, DASS_BLOCK_SIZE)
        if not batch:
            return self._finish_instrument()
        self.pending_item = batch[0].number
        return {
            "phase": "instrument",
            "items": [_item_payload(i) for i in batch],
            "progress": {"answered": len(self.dass), "total": len(dass21.ITEMS)},
        }

    def _finish_instrument(self) -> dict:
        result = dass21.score(self.dass)
        self.pending_item = None
        self.phase = Phase.POST
        db.save_score(self.conn, self.pseudonym, self.session_id, "dass21", {
            "raw": result.raw, "scaled": result.scaled, "bands": result.bands,
        })
        return {
            "phase": "post",
            "result": {
                "bands": result.bands,
                "scaled": result.scaled,
                "summary": result.plain_summary(),
                "referral_indicated": result.referral_indicated,
            },
            "message": (
                "That's all 21. These are screening bands, not a diagnosis — they describe "
                "the past week, not you."
            ),
            "offer_referral": result.referral_indicated or self.peak_risk >= safety.Risk.ELEVATED,
        }

    # -- helpers -------------------------------------------------------------

    def _should_offer(self) -> bool:
        if self.dass_offered or self.dass_declined or self.dass:
            return False
        if len([h for h in self.history if h["role"] == "user"]) < MIN_TURNS_BEFORE_OFFER:
            return False
        return self.peak_risk >= safety.Risk.WATCH

    def _harvest_lifestyle(self, text: str) -> None:
        found = llm.extract(prompts.LIFESTYLE_EXTRACTION, text, prompts.LIFESTYLE_SCHEMA)
        for slot, value in found.items():
            if slot not in lifestyle.SLOTS:
                continue
            try:
                self.profile.fill(slot, value, quote=text[:200])
                db.save_lifestyle(self.conn, self.pseudonym, self.session_id, slot, value, text[:200])
            except ValueError:
                pass

    def _undo_user_turn(self) -> None:
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()
            if self.mode is Mode.STORY:
                db.drop_last_turn(self.conn, self.pseudonym, self.session_id, "user")

    def _record(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if self.mode is Mode.STORY:
            db.save_turn(self.conn, self.pseudonym, self.session_id, role, content)

    # -- counsellor handoff --------------------------------------------------

    def handoff(self) -> dict:
        """The Level-5 dashboard payload. Every field is derived from something
        that actually happened. Nothing here is canned — if a section is empty,
        it renders empty, because an invented finding in a counsellor's briefing
        is worse than a blank one."""
        result = dass21.score(self.dass) if self.dass else None
        return {
            "pseudonym": self.pseudonym,
            "session_id": self.session_id,
            "mode": self.mode.value,
            "turns": len([h for h in self.history if h["role"] == "user"]),
            "screening": None if result is None else {
                "instrument": "DASS-21",
                "complete": result.complete,
                "answered": f"{result.answered}/21",
                "bands": result.bands,
                "scaled": result.scaled,
                "referral_indicated": result.referral_indicated,
                "items_for_review": result.review_flags,
            },
            "lifestyle": {
                "captured": self.profile.values,
                "concerns": self.profile.concerns(),
                "coverage": round(self.profile.coverage, 2),
            },
            "risk": {
                "peak_level": self.peak_risk.name,
                "notes": self.risk_notes,
            },
            "longitudinal": (
                db.score_history(self.conn, self.pseudonym) if self.mode is Mode.STORY else []
            ),
            "caveat": (
                "Screening indication only. Generated from a conversation with a 3B "
                "language model and deterministic scoring. Not a diagnosis and not a "
                "substitute for clinical judgement."
            ),
        }


def _item_payload(item: dass21.Item) -> dict:
    return {
        "number": item.number,
        "text": item.text,
        "anchors": dass21.ANCHORS,
        "time_frame": dass21.TIME_FRAME,
    }
