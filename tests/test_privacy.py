"""
Incognito must mean incognito.

The privacy notice tells a student that Incognito "keeps nothing". The one
disclosed exception is the safeguarding record: if they say something that
suggests they may be in danger, *that it happened* (not what they said) is
logged. Everything else — chat turns, questionnaire answers, scores, lifestyle
details, and the fact of having taken part — must stay in memory.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, llm, main
from app.ai_client import AIClient
from app.instruments import dass21

CONTENT_TABLES = ("turns", "instrument_responses", "instrument_scores", "lifestyle", "consent")


@pytest.fixture
def api(mock_ai):
    llm.set_client(AIClient(mock_ai.url, timeout=5, retry_backoff=(0, 0)))
    mock_ai.json_reply = '{"sleep_hours": 4}'          # the model "extracts" a lifestyle detail
    return TestClient(main.app)


def counts(pseudonym):
    """Row counts per table for one pseudonym, read straight from the file."""
    con = sqlite3.connect("iturn.db")
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t} WHERE pseudonym=?", (pseudonym,)).fetchone()[0]
                for t in (*CONTENT_TABLES, "risk_events")}
    finally:
        con.close()


def full_session(api, mode, pseudonym):
    """Talk, get offered the questionnaire, answer all 21 items, end."""
    sid = api.post("/api/start", json={"pseudonym": pseudonym, "mode": mode}).json()["session_id"]
    for text in ["hey", "I only sleep like 4 hours", "feeling hopeless about placements",
                 "can't focus", "so tired", "yeah it's been weeks"]:
        assert api.post("/api/turn", json={"session_id": sid, "text": text}).status_code == 200
    assert api.post("/api/instrument/accept", json={"session_id": sid}).status_code == 200
    for item in dass21.ITEMS:
        r = api.post("/api/instrument/answer", json={"session_id": sid, "item": item.number, "value": 2})
        assert r.status_code == 200
    assert api.post("/api/end", json={"session_id": sid}).status_code == 200
    return sid


def test_story_mode_does_persist_everything(api):
    """Positive control: if this fails, the incognito assertions below prove nothing."""
    full_session(api, "story", "U_STORY")
    c = counts("U_STORY")
    assert c["turns"] > 0 and c["instrument_responses"] == 21 and c["instrument_scores"] == 1
    assert c["lifestyle"] > 0 and c["consent"] == 1


def test_incognito_persists_no_content_at_all(api):
    full_session(api, "incognito", "U_INCOG")
    c = counts("U_INCOG")
    assert {t: c[t] for t in CONTENT_TABLES} == {t: 0 for t in CONTENT_TABLES}, c
    assert c["risk_events"] == 0                       # nothing crossed the safeguarding threshold


def test_incognito_still_shows_the_student_their_own_results_in_memory(api):
    """Keeping nothing on disk must not break the live session."""
    sid = api.post("/api/start", json={"pseudonym": "U_MEM", "mode": "incognito"}).json()["session_id"]
    for i, text in enumerate(["hey", "I only sleep like 4 hours", "hopeless", "tired", "meh", "weeks"]):
        api.post("/api/turn", json={"session_id": sid, "text": text})
    api.post("/api/instrument/accept", json={"session_id": sid})
    for item in dass21.ITEMS:
        api.post("/api/instrument/answer", json={"session_id": sid, "item": item.number, "value": 3})
    s = main.SESSIONS[sid]
    assert len(s.dass) == 21 and s.profile.values.get("sleep_hours") == 4
    close = api.post("/api/end", json={"session_id": sid}).json()["report"]
    assert close["ephemeral"] and close["screening_bands"]["depression"] == "Extremely severe"


def test_incognito_risk_event_is_the_one_disclosed_exception(api):
    sid = api.post("/api/start", json={"pseudonym": "U_RISK", "mode": "incognito"}).json()["session_id"]
    api.post("/api/turn", json={"session_id": sid, "text": "I keep getting panic attacks before vivas"})
    c = counts("U_RISK")
    assert c["risk_events"] == 1
    assert {t: c[t] for t in CONTENT_TABLES} == {t: 0 for t in CONTENT_TABLES}
    # ...and what is stored is that it happened, not what was said.
    con = sqlite3.connect("iturn.db")
    stored = " ".join(str(v) for row in con.execute("SELECT * FROM risk_events") for v in row)
    con.close()
    assert "panic attacks before vivas" not in stored


def test_incognito_data_cannot_leak_into_a_story_session_of_the_same_name(api):
    """A student who used Incognito, then Story under the same pseudonym, must not
    inherit questionnaire scores or lifestyle details from the Incognito visit."""
    full_session(api, "incognito", "U_SAME")
    sid = api.post("/api/start", json={"pseudonym": "U_SAME", "mode": "story"}).json()["session_id"]
    conn = main.SESSIONS[sid].conn
    assert db.score_history(conn, "U_SAME") == []
    assert main.SESSIONS[sid].handoff()["longitudinal"] == []


def test_the_module_docstring_no_longer_lies():
    """The old docstring claimed Incognito opens and writes nothing. State the truth."""
    assert "Incognito Mode touches none of this. Nothing is opened, nothing is written." not in db.__doc__
    assert "risk" in db.__doc__.lower() and "incognito" in db.__doc__.lower()


@pytest.mark.parametrize("writer,args", [
    (db.save_response, ("dass21", 1, 2)),
    (db.save_score, ("dass21", {"raw": {}})),
    (db.save_lifestyle, ("sleep_hours", 4, "I sleep 4 hours")),
])
def test_each_writer_refuses_without_consent(writer, args):
    conn = db.connect()
    writer(conn, "U_NOCONSENT", "s1", *args)
    assert sum(counts("U_NOCONSENT")[t] for t in CONTENT_TABLES) == 0


@pytest.mark.parametrize("writer,args,table", [
    (db.save_response, ("dass21", 1, 2), "instrument_responses"),
    (db.save_score, ("dass21", {"raw": {}}), "instrument_scores"),
    (db.save_lifestyle, ("sleep_hours", 4, "I sleep 4 hours"), "lifestyle"),
])
def test_each_writer_works_with_consent(writer, args, table):
    conn = db.connect()
    db.grant_consent(conn, "U_CONSENT", "s1", "store_conversation")
    writer(conn, "U_CONSENT", "s1", *args)
    assert counts("U_CONSENT")[table] == 1


def test_consent_for_one_session_does_not_cover_another(api):
    conn = db.connect()
    db.grant_consent(conn, "U_X", "story-session", "store_conversation")
    db.save_lifestyle(conn, "U_X", "incognito-session", "sleep_hours", 4, "q")
    assert counts("U_X")["lifestyle"] == 0
