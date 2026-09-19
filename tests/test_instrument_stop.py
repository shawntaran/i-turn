"""
"You can stop at any point" — the questionnaire offer says so, so it has to be true.

Stopping ends the questionnaire without scoring the partial answers into bands
(for the student or as a referral), returns to ordinary conversation, and does
not re-offer it this session.
"""

import pytest
from fastapi.testclient import TestClient

from app import llm, main
from app.ai_client import AIClient


@pytest.fixture
def api(mock_ai):
    llm.set_client(AIClient(mock_ai.url, timeout=5, retry_backoff=(0, 0)))
    return TestClient(main.app)


def turn(api, sid, text):
    r = api.post("/api/turn", json={"session_id": sid, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def into_questionnaire(api, mode="incognito", pseudonym="U_STOP"):
    sid = api.post("/api/start", json={"pseudonym": pseudonym, "mode": mode}).json()["session_id"]
    for t in ["hey", "feeling hopeless about placements", "still hopeless", "can't focus",
              "so tired", "yeah it's been weeks"]:
        out = turn(api, sid, t)
    assert "offer" in out
    assert api.post("/api/instrument/accept", json={"session_id": sid}).json()["phase"] == "instrument"
    return sid


def answer(api, sid, item, value=2):
    return api.post("/api/instrument/answer", json={"session_id": sid, "item": item, "value": value})


def test_stop_returns_to_conversation(api, mock_ai):
    sid = into_questionnaire(api)
    for i in (1, 2, 3):
        assert answer(api, sid, i).status_code == 200

    r = api.post("/api/instrument/stop", json={"session_id": sid})
    assert r.status_code == 200
    body = r.json()
    assert body["phase"] == "open" and "completely fine" in body["message"]

    out = turn(api, sid, "thanks, let's just talk")
    assert out["message"] == mock_ai.reply            # an ordinary reply from the model...
    assert "item" not in out and "needs_explicit" not in out    # ...not the questionnaire path


def test_it_is_not_offered_again_this_session(api):
    sid = into_questionnaire(api)
    api.post("/api/instrument/stop", json={"session_id": sid})
    for t in ["still hopeless", "really hopeless", "so tired", "nothing helps"]:
        assert "offer" not in turn(api, sid, t)
    assert main.SESSIONS[sid].dass_declined is True


def test_partial_answers_are_never_scored_into_bands(api):
    sid = into_questionnaire(api)
    for i in (1, 2, 3, 4):
        answer(api, sid, i, value=3)                   # would look severe if it were scored
    api.post("/api/instrument/stop", json={"session_id": sid})

    h = api.app.state if False else main.SESSIONS[sid].handoff()
    assert h["screening"]["complete"] is False and h["screening"]["answered"] == "4/21"

    report = api.post("/api/end", json={"session_id": sid}).json()["report"]
    assert report["screening_bands"] is None           # the student is never shown partial bands


def test_stopping_in_story_mode_also_shows_no_bands(api):
    sid = into_questionnaire(api, mode="story", pseudonym="U_STOP2")
    for i in (1, 2, 3):
        answer(api, sid, i)
    api.post("/api/instrument/stop", json={"session_id": sid})
    report = api.post("/api/end", json={"session_id": sid}).json()["report"]
    assert report["screening_bands"] is None


def test_stop_works_even_with_the_ai_server_down(api):
    """Stopping is deterministic; it must not need the model."""
    sid = into_questionnaire(api)
    llm.set_client(AIClient("http://127.0.0.1:9", timeout=2, retries=0))
    r = api.post("/api/instrument/stop", json={"session_id": sid})
    assert r.status_code == 200 and r.json()["phase"] == "open"


def test_stop_outside_a_questionnaire_is_harmless(api):
    sid = api.post("/api/start", json={"pseudonym": "U_STOP3", "mode": "incognito"}).json()["session_id"]
    r = api.post("/api/instrument/stop", json={"session_id": sid})
    assert r.status_code == 200 and r.json()["phase"] == "open"


def test_stop_cannot_lift_a_crisis_halt(api):
    sid = api.post("/api/start", json={"pseudonym": "U_STOP4", "mode": "incognito"}).json()["session_id"]
    assert turn(api, sid, "I don't want to live anymore")["session_halted"]
    r = api.post("/api/instrument/stop", json={"session_id": sid})
    assert r.json()["phase"] == "halted"
    assert turn(api, sid, "ok").get("session_halted")


def test_stop_on_an_unknown_session_is_404(api):
    assert api.post("/api/instrument/stop", json={"session_id": "nope"}).status_code == 404
