"""
The whole application against an AI server that behaves, and one that doesn't.
UI -> FastAPI backend -> AIClient -> (mock) AI server. The property under test:
whatever goes wrong with the model, the student gets a readable sentence — not a
traceback — and the session is left in a state where they can just try again.
"""

import pytest
from fastapi.testclient import TestClient

from app import db, llm, main
from app.ai_client import AIClient
from tests.conftest import free_port


@pytest.fixture
def api(mock_ai):
    llm.set_client(AIClient(mock_ai.url, timeout=5))
    return TestClient(main.app)


def begin(api, mode="incognito", pseudonym="U_TEST"):
    r = api.post("/api/start", json={"pseudonym": pseudonym, "mode": mode})
    assert r.status_code == 200
    return r.json()["session_id"]


def say(api, sid, text):
    return api.post("/api/turn", json={"session_id": sid, "text": text})


def point_at_dead_server():
    llm.set_client(AIClient(f"http://127.0.0.1:{free_port()}", timeout=5))


# -- it works ---------------------------------------------------------------------

def test_turn_goes_through_the_ai_server(api, mock_ai):
    sid = begin(api)
    r = say(api, sid, "exams are rough")
    assert r.status_code == 200
    assert r.json()["message"] == mock_ai.reply

    chat = [q["json"] for q in mock_ai.requests if not q["json"].get("json_mode")][-1]
    assert "I-Turn" in chat["system_prompt"]
    assert chat["messages"][-1] == {"role": "user", "content": "exams are rough"}


def test_lifestyle_extraction_uses_the_same_contract(api, mock_ai):
    mock_ai.json_reply = '{"sleep_hours": 4}'
    sid = begin(api)
    say(api, sid, "I only sleep like 4 hours")
    assert main.SESSIONS[sid].profile.values.get("sleep_hours") == 4
    extraction = [q["json"] for q in mock_ai.requests if q["json"].get("json_mode")][0]
    assert extraction["temperature"] == 0.0 and extraction["max_tokens"] == 128


def test_meta_is_unchanged_for_the_ui(api):
    body = api.get("/api/meta").json()
    assert {"languages", "privacy_notice", "crisis_resources"} <= set(body)


# -- the model is unreachable -------------------------------------------------------------

def test_ai_server_down_gives_a_readable_error_not_a_traceback(api):
    sid = begin(api)
    point_at_dead_server()
    r = say(api, sid, "hello")
    assert r.status_code == 503
    body = r.json()
    # `detail` is the field the existing UI already displays.
    assert body["detail"].startswith("AI service unavailable.")
    assert "AI_BASE_URL" in body["detail"]
    assert body["error"]["code"] == "unavailable"
    assert "Traceback" not in r.text and "httpx" not in r.text and "127.0.0.1" not in r.text


@pytest.mark.parametrize("mode,code,fragment", [
    ("slow", "timeout", "too long"),
    ("malformed", "invalid_response", "could not be used"),
    ("oom", "out_of_memory", "GPU memory"),
    ("model_error", "model_error", "failed to load"),
    ("loading", "model_loading", "still loading"),
    ("interrupt", "interrupted", "interrupted"),
    ("unauthorized", "unauthorized", "AI_API_KEY"),
])
def test_each_failure_mode_reaches_the_student_as_a_sentence(mock_ai, mode, code, fragment):
    mock_ai.delay = 1.5
    llm.set_client(AIClient(mock_ai.url, timeout=0.4 if mode == "slow" else 5))
    api = TestClient(main.app)
    sid = begin(api)
    mock_ai.mode = mode
    r = say(api, sid, "hello")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == code
    assert fragment in r.json()["detail"]
    assert "Traceback" not in r.text


def test_app_starts_and_serves_even_if_the_ai_server_is_down():
    """Startup runs a health probe. It must warn, never crash."""
    point_at_dead_server()
    with TestClient(main.app) as c:
        assert c.get("/api/meta").status_code == 200


# -- and the session survives it ---------------------------------------------------------------

def test_failed_turn_can_simply_be_retried_in_story_mode(api, mock_ai):
    sid = begin(api, mode="story", pseudonym="U_RETRY")
    mock_ai.mode = "oom"
    assert say(api, sid, "I can't sleep").status_code == 503

    s = main.SESSIONS[sid]
    assert s.history == []                                          # nothing dangling in memory
    assert db.turns_for(s.conn, "U_RETRY", sid) == []               # ...or on disk

    mock_ai.mode = "ok"
    assert say(api, sid, "I can't sleep").status_code == 200
    roles = [t["role"] for t in db.turns_for(s.conn, "U_RETRY", sid)]
    assert roles == ["user", "assistant"]                           # stored once, not twice


def test_a_failed_turn_does_not_use_up_the_questionnaire_offer(api, mock_ai):
    sid = begin(api)
    for text in ["hey", "feeling really hopeless about placements", "still hopeless",
                 "can't focus", "so tired"]:
        assert say(api, sid, text).status_code == 200

    mock_ai.mode = "oom"                       # the turn that would have made the offer
    assert say(api, sid, "yeah it's been weeks").status_code == 503
    assert main.SESSIONS[sid].dass_offered is False

    mock_ai.mode = "ok"
    r = say(api, sid, "yeah it's been weeks")
    assert r.status_code == 200 and "offer" in r.json()


# -- the deterministic parts don't need the model at all ----------------------------------------

def test_crisis_response_never_depends_on_the_ai_server(api):
    sid = begin(api)
    point_at_dead_server()
    r = say(api, sid, "I don't want to live anymore")
    assert r.status_code == 200
    body = r.json()
    assert body["session_halted"] and "14416" in body["message"]


def test_questionnaire_works_with_the_ai_server_down(api):
    sid = begin(api)
    point_at_dead_server()
    r = api.post("/api/instrument/accept", json={"session_id": sid})
    assert r.status_code == 200 and r.json()["phase"] == "instrument"

    # Free text mid-questionnaire would normally ask the model to read a rating.
    # With the model gone it falls back to the explicit buttons, as designed.
    r = say(api, sid, "kind of, sometimes")
    assert r.status_code == 200 and r.json()["needs_explicit"] is True

    r = api.post("/api/instrument/answer", json={"session_id": sid, "item": 1, "value": 2})
    assert r.status_code == 200


# -- health ---------------------------------------------------------------------------------------

def test_ai_health_ok(api):
    r = api.get("/api/ai/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ai_health_unreachable(api):
    point_at_dead_server()
    r = api.get("/api/ai/health")
    assert r.status_code == 503
    assert r.json()["status"] == "unreachable" and r.json()["code"] == "unavailable"


def test_ai_health_loading(mock_ai):
    llm.set_client(AIClient(mock_ai.url, timeout=5))
    mock_ai.mode = "health_loading"
    r = TestClient(main.app).get("/api/ai/health")
    assert r.status_code == 503 and r.json()["status"] == "loading"
