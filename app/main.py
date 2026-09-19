"""
I-Turn prototype server.

Deliberately thin. All the judgement lives in session.py, safety.py and the
instrument modules; this file just moves JSON around.

Run:
    ollama serve &
    ollama pull qwen2.5:3b-instruct-q4_K_M
    uvicorn app.main:app --reload --port 8000

No-GPU dev:
    ITURN_BACKEND=stub uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, llm, prompts, report, safety
from .instruments import dass21
from .session import Mode, Session

app = FastAPI(title="I-Turn prototype")

SESSIONS: dict[str, Session] = {}   # in-memory; Phase 2 = Redis or signed cookies
STATIC = Path(__file__).parent.parent / "static"

PRIVACY_NOTICE = (
    "Two things before we start, plainly.\n\n"
    "**Incognito** keeps nothing. Close the tab and this conversation is gone — "
    "there is no copy.\n\n"
    "**Story** remembers you between visits under a made-up name you choose, so "
    "you don't start from scratch each time. You can delete all of it whenever "
    "you want.\n\n"
    "One exception, in both modes: if you say something that suggests you might "
    "be in danger, a record that it happened goes to the counselling department. "
    "Not what you said — that it happened. We'd rather tell you that now than "
    "surprise you with it later."
)


class StartRequest(BaseModel):
    pseudonym: str = Field(min_length=3, max_length=40)
    mode: Mode = Mode.INCOGNITO
    language: str = "English"


class TurnRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=4000)


class AnswerRequest(BaseModel):
    session_id: str
    item: int
    value: int


class ChoiceRequest(BaseModel):
    session_id: str


def _get(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(404, "session not found — start a new one")
    return s


@app.get("/api/meta")
def meta() -> dict:
    return {
        "model": llm.MODEL,
        "backend": llm.BACKEND,
        "languages": prompts.LANGUAGES,
        "privacy_notice": PRIVACY_NOTICE,
        "crisis_resources": safety.CRISIS_RESOURCES,
    }


@app.post("/api/start")
def start(req: StartRequest) -> dict:
    s = Session(pseudonym=req.pseudonym, mode=req.mode, language=req.language)
    s.start()
    SESSIONS[s.session_id] = s
    return {
        "session_id": s.session_id,
        "mode": s.mode.value,
        "returning": bool(s.history),
    }


@app.post("/api/turn")
def turn(req: TurnRequest) -> dict:
    return _get(req.session_id).turn(req.text)


@app.post("/api/instrument/accept")
def accept(req: ChoiceRequest) -> dict:
    return _get(req.session_id).accept_instrument()


@app.post("/api/instrument/decline")
def decline(req: ChoiceRequest) -> dict:
    return _get(req.session_id).decline_instrument()


@app.post("/api/instrument/answer")
def answer(req: AnswerRequest) -> dict:
    try:
        return _get(req.session_id).answer_item(req.item, req.value)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/end")
def end(req: ChoiceRequest) -> dict:
    """
    Explicit end of session. Until this existed, closing the tab was the only
    exit and it produced nothing — the Session object died with its data still
    sitting in SQLite, unreachable.

    Incognito has nothing on disk, so it gets the in-memory handoff, once, and
    then it's gone for good. That's the deal the student agreed to.
    """
    s = _get(req.session_id)
    is_story = s.mode is Mode.STORY
    close = (
        report.student_close(s.conn, s.pseudonym, s.session_id)
        if is_story else
        {
            "session_id": s.session_id,
            "ephemeral": True,
            "screening_bands": (
                dass21.score(s.dass).bands if s.dass and dass21.score(s.dass).complete else None
            ),
            "screening_note": (
                "Incognito — nothing was kept. This is the only time you'll see it."
            ),
            "next": ["Story mode remembers you between visits, if you ever want that."],
        }
    )
    SESSIONS.pop(req.session_id, None)
    return {"closed": True, "mode": s.mode.value, "report": close}


@app.get("/api/report/{pseudonym}/{session_id}")
def student_report(pseudonym: str, session_id: str) -> dict:
    """Student's own view of a past Story-mode session. Rebuilt from SQLite,
    so it works long after the tab closed."""
    conn = db.connect()
    r = report.student_close(conn, pseudonym, session_id)
    if r["when"] is None:
        raise HTTPException(404, "no stored session by that id")
    return r


@app.get("/api/sessions/{pseudonym}")
def sessions(pseudonym: str) -> dict:
    return {"pseudonym": pseudonym, "sessions": db.sessions_for(db.connect(), pseudonym)}


@app.get("/api/handoff/{session_id}")
def handoff(session_id: str) -> dict:
    """Live in-memory handoff. Works only while the session is open — kept for
    the Incognito case, where there is nothing on disk to rebuild from."""
    return _get(session_id).handoff()


@app.get("/api/counsellor/{pseudonym}/{session_id}")
def counsellor(pseudonym: str, session_id: str,
               transcript: bool = False, text: bool = False):
    """
    Level-5 briefing, rebuilt from disk.

    NO AUTH. This is the prototype's single biggest hole — it serves a
    counsellor's screen to anyone who can guess a pseudonym. Put this behind
    real authentication before it leaves localhost.
    """
    conn = db.connect()
    h = report.counsellor_handoff(conn, pseudonym, session_id, include_transcript=transcript)
    if h["student"]["when"] is None:
        raise HTTPException(404, "no stored session by that id")
    if text:
        return PlainTextResponse(report.as_text(h))
    return h


@app.post("/api/counsellor/{pseudonym}/{session_id}/acknowledge")
def acknowledge(pseudonym: str, session_id: str) -> dict:
    return {"updated": db.acknowledge_risk(db.connect(), pseudonym, session_id)}


@app.delete("/api/data/{pseudonym}")
def erase(pseudonym: str) -> dict:
    conn = db.connect()
    return {"deleted": db.erase(conn, pseudonym), "note": "risk events retained per protocol"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
