"""
Reports.

Two projections of the same stored session, for two different readers:

  student_close()      — what the student sees when they end a session.
  counsellor_handoff() — the Level-5 briefing, behind auth.

Both read from SQLite, not from a live Session object, so a session can be
pulled up days later. The live handoff on Session stays for the in-memory
Incognito case, where there is nothing on disk to read.

The split is not cosmetic. The counsellor view contains things the student was
never told about themselves — risk flags, items marked for review, a referral
indication. Handing someone "Depression: Severe" as a parting screen with
nobody in the room is a bad way to end a conversation. The student close says
less, on purpose.

Nothing in this file produces a finding that isn't in the database. If a
section has no data it renders empty. The earlier prototype's
generate_summary() returned "sustained academic stress, emerging sleep
disruption" no matter what — that is the specific failure this file exists to
avoid.
"""

from __future__ import annotations

import datetime as dt

from . import db
from .instruments import dass21, lifestyle
from .safety import Risk

GENERATED_BY = "I-Turn prototype · Qwen2.5-3B local · deterministic scoring"

CAVEAT = (
    "Screening indication only. Produced from a conversation with a 3B language "
    "model plus deterministic scoring. Not a diagnosis, not a clinical "
    "assessment, and not a substitute for the counsellor's own judgement."
)


def _duration(turns: list[dict]) -> str:
    if len(turns) < 2:
        return "—"
    try:
        a = dt.datetime.fromisoformat(turns[0]["ts"])
        b = dt.datetime.fromisoformat(turns[-1]["ts"])
    except ValueError:
        return "—"
    mins = int((b - a).total_seconds() // 60)
    return f"{mins} min" if mins else "under a minute"


def _screening(responses: dict[int, int]) -> dict | None:
    """None when the student never started the questionnaire. That is a real
    and common outcome — it renders as 'not taken', never as an empty score."""
    if not responses:
        return None
    r = dass21.score(responses)
    return {
        "instrument": "DASS-21",
        "complete": r.complete,
        "answered": f"{r.answered}/21",
        "bands": r.bands,
        "scaled": r.scaled,
        "raw": r.raw,
        "referral_indicated": r.referral_indicated,
        "items_for_review": [
            {"item": n, "text": dass21.BY_NUMBER[n].text, "response": responses[n]}
            for n in r.review_flags
        ],
        "partial_warning": (
            None if r.complete else
            "Incomplete. Subscale scores are provisional and bands should not be "
            "read against published norms."
        ),
    }


# ---------------------------------------------------------------------------
# Student-facing
# ---------------------------------------------------------------------------

def student_close(conn, pseudonym: str, session_id: str) -> dict:
    turns = db.turns_for(conn, pseudonym, session_id)
    responses = db.responses_for(conn, pseudonym, session_id)
    life = db.lifestyle_for(conn, pseudonym, session_id)

    screening = _screening(responses)

    # What they told us about their own life, in their words, back to them.
    noticed = []
    for slot, (value, quote) in life.items():
        label = lifestyle.SLOTS.get(slot, ("", slot))[1]
        noticed.append({"about": label, "you_said": quote or str(value)})

    bands = None
    if screening and screening["complete"]:
        bands = screening["bands"]

    return {
        "session_id": session_id,
        "when": turns[0]["ts"] if turns else None,
        "length": _duration(turns),
        "you_talked_about": noticed,
        "screening_bands": bands,
        "screening_note": (
            "These describe the past week, not you. They're a starting point for "
            "a conversation, not a label."
            if bands else
            "You didn't take the questionnaire this time. That's completely fine — "
            "it's there whenever you want it."
        ),
        "next": [
            "Come back anytime. In Story mode I'll remember where we left off.",
            "You can book a counsellor without explaining yourself first — they'll "
            "already have the background if you want them to.",
            "Delete everything I've kept, whenever you want, no questions.",
        ],
        # Deliberately absent from this view: risk flags, items_for_review,
        # referral_indicated. Those go to a human, not to a parting screen.
    }


# ---------------------------------------------------------------------------
# Counsellor-facing
# ---------------------------------------------------------------------------

def counsellor_handoff(conn, pseudonym: str, session_id: str,
                       include_transcript: bool = False) -> dict:
    turns = db.turns_for(conn, pseudonym, session_id)
    responses = db.responses_for(conn, pseudonym, session_id)
    life = db.lifestyle_for(conn, pseudonym, session_id)
    risk = db.risk_for(conn, pseudonym)               # full history, not one session
    history = db.score_history(conn, pseudonym)       # longitudinal DASS

    profile = lifestyle.LifestyleProfile()
    for slot, (value, quote) in life.items():
        try:
            profile.fill(slot, value, quote)
        except ValueError:
            pass

    this_session_risk = [r for r in risk if r["session_id"] == session_id]
    peak = max((r["level"] for r in this_session_risk), default=0)

    return {
        "generated_by": GENERATED_BY,
        "caveat": CAVEAT,

        "student": {
            "pseudonym": pseudonym,
            "session_id": session_id,
            "when": turns[0]["ts"] if turns else None,
            "length": _duration(turns),
            "student_turns": sum(1 for t in turns if t["role"] == "user"),
            "sessions_on_record": len(db.sessions_for(conn, pseudonym)),
        },

        "screening": _screening(responses),

        "lifestyle": {
            "captured": profile.values,
            "in_their_words": {s: q for s, (v, q) in life.items() if q},
            "concerns": profile.concerns(),
            "coverage": round(profile.coverage, 2),
        },

        "risk": {
            "peak_this_session": Risk(peak).name,
            "this_session": this_session_risk,
            "prior_sessions": [r for r in risk if r["session_id"] != session_id],
            "unacknowledged": sum(1 for r in risk if not r["acknowledged"]),
        },

        "longitudinal": history,

        "transcript": turns if include_transcript else None,
        "transcript_note": (
            None if include_transcript else
            "Withheld. Request explicitly — the student consented to storage, not "
            "to the transcript being the default view."
        ),
    }


# ---------------------------------------------------------------------------
# Plain text, for a counsellor who wants to read it rather than parse it
# ---------------------------------------------------------------------------

def as_text(handoff: dict) -> str:
    s, sc, lf, rk = (handoff["student"], handoff["screening"],
                     handoff["lifestyle"], handoff["risk"])
    L: list[str] = []
    add = L.append

    add("I-TURN SESSION HANDOFF")
    add("=" * 60)
    add(f"Student:  {s['pseudonym']}   Session: {s['session_id']}")
    add(f"When:     {s['when']}   ({s['length']}, {s['student_turns']} turns)")
    add(f"History:  {s['sessions_on_record']} session(s) on record")
    add("")

    add("SCREENING")
    add("-" * 60)
    if sc is None:
        add("  DASS-21 not taken this session.")
    else:
        add(f"  DASS-21 — {sc['answered']} answered")
        for k in ("depression", "anxiety", "stress"):
            add(f"    {k.capitalize():12} {sc['scaled'][k]:>3}   {sc['bands'][k]}")
        if sc["partial_warning"]:
            add(f"  ! {sc['partial_warning']}")
        if sc["referral_indicated"]:
            add("  ! Referral indicated by screening thresholds.")
        for item in sc["items_for_review"]:
            add(f"  ! Item {item['item']} answered {item['response']}: {item['text']}")
    add("")

    add("RISK")
    add("-" * 60)
    add(f"  Peak this session: {rk['peak_this_session']}")
    if not rk["this_session"]:
        add("  No risk events this session.")
    for r in rk["this_session"]:
        add(f"  [{r['ts']}] level {r['level']} — {r['reason']}")
    if rk["prior_sessions"]:
        add(f"  {len(rk['prior_sessions'])} event(s) in earlier sessions.")
    if rk["unacknowledged"]:
        add(f"  ! {rk['unacknowledged']} unacknowledged.")
    add("")

    add("LIFESTYLE (volunteered, not asked)")
    add("-" * 60)
    if not lf["captured"]:
        add("  Nothing captured.")
    for slot, value in lf["captured"].items():
        quote = lf["in_their_words"].get(slot, "")
        add(f"  {slot:20} {value}")
        if quote:
            add(f"  {'':20} \u201c{quote[:80]}\u201d")
    for c in lf["concerns"]:
        add(f"  ! {c}")
    add("")

    if handoff["longitudinal"]:
        add("OVER TIME")
        add("-" * 60)
        for h in handoff["longitudinal"]:
            b = h.get("bands", {})
            add(f"  {h['ts'][:10]}  D:{b.get('depression','—')}  "
                f"A:{b.get('anxiety','—')}  S:{b.get('stress','—')}")
        add("")

    add("-" * 60)
    add(handoff["caveat"])
    return "\n".join(L)
