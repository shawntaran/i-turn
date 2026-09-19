"""
Routes that read or delete stored student data need a counsellor token.

Until now GET /api/counsellor/{pseudonym}/{session_id} (transcripts, DASS scores,
lifestyle quotes), the handoff/report/session-list routes and DELETE
/api/data/{pseudonym} answered anyone who could reach the server. The student
UI calls none of them, so locking them changes nothing a student sees.

The rules: fail closed when no token is configured; Bearer header only (a token
in a URL ends up in logs and browser history); constant-time comparison.
"""

import pytest
from fastapi.testclient import TestClient

from app import db, llm, main
from app.ai_client import AIClient

TOKEN = "t0ken-" + "x" * 32


@pytest.fixture
def api(mock_ai):
    llm.set_client(AIClient(mock_ai.url, timeout=5, retry_backoff=(0, 0)))
    return TestClient(main.app)


@pytest.fixture
def seeded(api):
    """A finished Story session, so the locked routes have something real to serve."""
    sid = api.post("/api/start", json={"pseudonym": "U_AUTH", "mode": "story"}).json()["session_id"]
    for text in ["hey", "can't sleep"]:
        api.post("/api/turn", json={"session_id": sid, "text": text})
    api.post("/api/end", json={"session_id": sid})
    return sid


def locked_routes(sid):
    return [
        ("GET", f"/api/counsellor/U_AUTH/{sid}"),
        ("GET", f"/api/counsellor/U_AUTH/{sid}?transcript=true"),
        ("GET", f"/api/counsellor/U_AUTH/{sid}?text=true"),
        ("POST", f"/api/counsellor/U_AUTH/{sid}/acknowledge"),
        ("GET", f"/api/handoff/{sid}"),
        ("GET", f"/api/report/U_AUTH/{sid}"),
        ("GET", "/api/sessions/U_AUTH"),
        ("DELETE", "/api/data/U_AUTH"),
    ]


# -- no token configured: closed, not open --------------------------------------------

def test_every_locked_route_fails_closed_when_no_token_is_configured(api, seeded, monkeypatch):
    monkeypatch.delenv("ITURN_COUNSELLOR_TOKEN", raising=False)
    for method, path in locked_routes(seeded):
        r = api.request(method, path)
        assert r.status_code == 503, (method, path, r.status_code)
        assert "not configured" in r.json()["detail"]
    # ...and nothing was deleted by the attempt
    assert db.sessions_for(db.connect(), "U_AUTH")


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_token_counts_as_not_configured(api, seeded, monkeypatch, blank):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", blank)
    assert api.get(f"/api/counsellor/U_AUTH/{seeded}", headers={"Authorization": "Bearer "}).status_code == 503


# -- token configured: 401 unless correct -------------------------------------------------

@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong"},
    {"Authorization": "Bearer "},
    {"Authorization": TOKEN},                       # missing the "Bearer " scheme
    {"Authorization": f"Basic {TOKEN}"},
    {"Authorization": f"Bearer {TOKEN}x"},           # one character too long
    {"Authorization": f"Bearer {TOKEN[:-1]}"},       # one character too short
    {"Authorization": f"Bearer {TOKEN.upper()}"},    # case matters
])
def test_wrong_or_missing_credentials_are_401(api, seeded, monkeypatch, headers):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", TOKEN)
    for method, path in locked_routes(seeded):
        r = api.request(method, path, headers=headers)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.headers["www-authenticate"] == "Bearer"
        assert "U_AUTH" not in r.text                # the refusal reveals nothing about the record


def test_a_token_in_the_url_is_not_accepted(api, seeded, monkeypatch):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", TOKEN)
    for q in (f"token={TOKEN}", f"access_token={TOKEN}", f"authorization=Bearer {TOKEN}"):
        assert api.get(f"/api/counsellor/U_AUTH/{seeded}?{q}").status_code == 401


def test_the_correct_token_gets_through(api, seeded, monkeypatch):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", TOKEN)
    h = {"Authorization": f"Bearer {TOKEN}"}
    r = api.get(f"/api/counsellor/U_AUTH/{seeded}", headers=h)
    assert r.status_code == 200 and r.json()["student"]["pseudonym"] == "U_AUTH"
    assert api.get(f"/api/counsellor/U_AUTH/{seeded}?transcript=true", headers=h).json()["transcript"]
    assert "I-TURN SESSION HANDOFF" in api.get(f"/api/counsellor/U_AUTH/{seeded}?text=true", headers=h).text
    assert api.get(f"/api/report/U_AUTH/{seeded}", headers=h).status_code == 200
    assert api.get("/api/sessions/U_AUTH", headers=h).json()["sessions"]
    assert api.post(f"/api/counsellor/U_AUTH/{seeded}/acknowledge", headers=h).status_code == 200


def test_bearer_scheme_is_case_insensitive_and_whitespace_tolerant(api, seeded, monkeypatch):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", f"  {TOKEN}  ")       # stray spaces in .env
    for scheme in ("Bearer", "bearer", "BEARER"):
        r = api.get(f"/api/counsellor/U_AUTH/{seeded}", headers={"Authorization": f"{scheme}  {TOKEN} "})
        assert r.status_code == 200


def test_a_non_ascii_credential_is_a_clean_401_not_a_crash(api, seeded, monkeypatch):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", TOKEN)
    r = api.get(f"/api/counsellor/U_AUTH/{seeded}", headers={"Authorization": "Bearer तोकन".encode("utf-8")})
    assert r.status_code == 401


def test_erase_needs_the_token_and_then_erases_but_keeps_safeguarding_records(api, seeded, monkeypatch):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", TOKEN)
    conn = db.connect()
    db.log_risk(conn, "U_AUTH", seeded, 2, "test event")

    assert api.delete("/api/data/U_AUTH").status_code == 401
    assert db.sessions_for(conn, "U_AUTH")                          # untouched

    r = api.delete("/api/data/U_AUTH", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.json()["deleted"]["turns"] > 0
    assert db.sessions_for(conn, "U_AUTH") == []
    assert len(db.risk_for(conn, "U_AUTH")) == 1                    # documented exception, pinned


# -- what must stay open --------------------------------------------------------------------

def test_the_student_routes_need_no_token(api, monkeypatch):
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", TOKEN)
    assert api.get("/api/meta").status_code == 200
    assert api.get("/").status_code == 200
    sid = api.post("/api/start", json={"pseudonym": "U_OPEN", "mode": "incognito"}).json()["session_id"]
    assert api.post("/api/turn", json={"session_id": sid, "text": "hi"}).status_code == 200
    assert api.post("/api/instrument/decline", json={"session_id": sid}).status_code == 200
    assert api.post("/api/end", json={"session_id": sid}).status_code == 200
    assert api.get("/api/ai/health").status_code == 200


def test_the_student_ui_calls_no_locked_route():
    """Guard against the UI quietly growing a dependency on a locked route."""
    import re
    from pathlib import Path
    html = (Path(main.STATIC) / "index.html").read_text(encoding="utf-8")
    called = set(re.findall(r"api\('(/api/[a-z/]+)", html))
    locked_prefixes = ("/api/counsellor", "/api/handoff", "/api/report", "/api/sessions", "/api/data")
    assert called and not [c for c in called if c.startswith(locked_prefixes)]


# -- the API's own documentation is not published by default ------------------------------------

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_interactive_docs_are_off_by_default(api, path):
    assert api.get(path).status_code == 404


# -- startup tells the developer -------------------------------------------------------------------

def test_startup_warns_when_counsellor_access_is_unconfigured(monkeypatch, caplog, mock_ai):
    import logging
    llm.set_client(AIClient(mock_ai.url, timeout=5))
    monkeypatch.delenv("ITURN_COUNSELLOR_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING, logger="iturn"):
        with TestClient(main.app):
            pass
    assert "ITURN_COUNSELLOR_TOKEN" in caplog.text


def test_startup_warns_about_a_weak_token(monkeypatch, caplog, mock_ai):
    import logging
    llm.set_client(AIClient(mock_ai.url, timeout=5))
    monkeypatch.setenv("ITURN_COUNSELLOR_TOKEN", "short")
    with caplog.at_level(logging.WARNING, logger="iturn"):
        with TestClient(main.app):
            pass
    assert "too short" in caplog.text
