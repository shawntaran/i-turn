"""
Scoring boundaries, safety cases and session flow — the deterministic core.
Ported from the original tests_smoke.py script; the checks are unchanged. The
session-flow test now talks to a mock AI server instead of the old in-process
stub backend.
"""

from collections import Counter

import pytest

from app import llm, safety, session
from app.ai_client import AIClient
from app.instruments import dass21


# --- scoring sanity ----------------------------------------------------------------

def test_scoring_extremes():
    r = dass21.score({i.number: 3 for i in dass21.ITEMS})
    assert r.raw == {"depression": 21, "anxiety": 21, "stress": 21}
    assert r.scaled == {"depression": 42, "anxiety": 42, "stress": 42}
    assert all(v == "Extremely severe" for v in r.bands.values())
    assert r.complete and r.referral_indicated

    r0 = dass21.score({i.number: 0 for i in dass21.ITEMS})
    assert all(v == "Normal" for v in r0.bands.values())
    assert not r0.referral_indicated


def test_band_boundaries():
    zero = {i.number: 0 for i in dass21.ITEMS}
    # depression scaled 14 == Moderate -> raw 7 -> one item at 3 + two at 2
    resp = {**zero, 3: 3, 5: 2, 10: 2}
    assert dass21.score(resp).scaled["depression"] == 14
    assert dass21.score(resp).bands["depression"] == "Moderate"
    # anxiety mild boundary scaled 8 -> raw 4
    resp2 = {**zero, 2: 3, 4: 1}
    assert dass21.score(resp2).bands["anxiety"] == "Mild"
    # stress moderate boundary: scaled 19 is impossible; 20 -> raw 10
    resp3 = {**zero, 1: 3, 6: 3, 8: 2, 11: 2}
    assert dass21.score(resp3).scaled["stress"] == 20
    assert dass21.score(resp3).bands["stress"] == "Moderate"


def test_subscale_coverage():
    assert Counter(i.subscale for i in dass21.ITEMS) == \
        {"depression": 7, "anxiety": 7, "stress": 7}
    assert len({i.number for i in dass21.ITEMS}) == 21


# --- safety ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("my phone died again", safety.Risk.NONE),
    ("I'm dying of boredom in this lecture", safety.Risk.NONE),
    ("honestly I don't want to live anymore", safety.Risk.CRISIS),
    ("I want to end it all", safety.Risk.CRISIS),
    ("the character wants to kill myself in my screenplay", safety.Risk.ELEVATED),
    ("I keep getting panic attacks before vivas", safety.Risk.ELEVATED),
    ("just feeling really hopeless about placements", safety.Risk.WATCH),
    ("had dosa for breakfast", safety.Risk.NONE),
])
def test_safety_levels(text, want):
    assert safety.assess(text).level == want


# --- session flow ----------------------------------------------------------------------------

def test_session_flow_to_questionnaire_and_handoff(mock_ai):
    llm.set_client(AIClient(mock_ai.url, timeout=5))
    s = session.Session(pseudonym="U_TEST", mode=session.Mode.INCOGNITO)
    s.start()
    for msg in ["hey", "exams are rough", "can't sleep much", "like 4 hours",
                "feeling hopeless honestly", "yeah it's been weeks"]:
        out = s.turn(msg)
    assert out["phase"] == "offering" and "offer" in out

    o = s.accept_instrument()
    assert [i["number"] for i in o["items"]] == [1, 2, 3]
    for i in dass21.ITEMS:
        o = s.answer_item(i.number, 2)
    assert o["phase"] == "post" and o["result"]["referral_indicated"]

    h = s.handoff()
    assert h["screening"]["complete"] and h["risk"]["peak_level"] == "WATCH"


def test_crisis_halts_the_session_and_stays_halted():
    s2 = session.Session(pseudonym="U_T2")
    s2.start()
    c = s2.turn("I don't want to live")
    assert c["session_halted"] and "14416" in c["message"]
    assert s2.turn("ok").get("session_halted")
