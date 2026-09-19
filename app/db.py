"""
Persistence.

Reworked from the earlier prototype's single `sessions` table. Changes that
matter:

  - Real per-session ids. The old code hardcoded session_id='session_active',
    so every conversation a pseudonym ever had merged into one blob.
  - Nothing is written until consent is recorded. Story Mode is a choice the
    student makes, and the choice itself is a row.
  - Instrument responses live in their own table, not as chat turns. They are
    data, not dialogue, and a counsellor needs to query them.
  - Risk events are append-only and never deleted by an erase request. That
    asymmetry needs the ethics committee's explicit sign-off — write it into
    the protocol, don't leave it as an engineering decision.

Incognito Mode touches none of this. Nothing is opened, nothing is written.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path("iturn.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS consent (
    pseudonym   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    granted_at  TEXT NOT NULL,
    scope       TEXT NOT NULL,   -- 'store_conversation' | 'link_department_data' | 'research'
    PRIMARY KEY (pseudonym, session_id, scope)
);

CREATE TABLE IF NOT EXISTS turns (
    pseudonym   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    ts          TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns ON turns (pseudonym, session_id, ts);

CREATE TABLE IF NOT EXISTS instrument_responses (
    pseudonym   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    instrument  TEXT NOT NULL,   -- 'dass21'
    item        INTEGER NOT NULL,
    response    INTEGER NOT NULL,
    confirmed   INTEGER NOT NULL DEFAULT 1,  -- 0 if model-inferred and unconfirmed
    ts          TEXT NOT NULL,
    PRIMARY KEY (pseudonym, session_id, instrument, item)
);

CREATE TABLE IF NOT EXISTS instrument_scores (
    pseudonym   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    instrument  TEXT NOT NULL,
    ts          TEXT NOT NULL,
    payload     TEXT NOT NULL    -- json
);

CREATE TABLE IF NOT EXISTS lifestyle (
    pseudonym   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    slot        TEXT NOT NULL,
    value       TEXT NOT NULL,
    quote       TEXT,
    ts          TEXT NOT NULL,
    PRIMARY KEY (pseudonym, session_id, slot)
);

CREATE TABLE IF NOT EXISTS risk_events (
    pseudonym   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    ts          TEXT NOT NULL,
    level       INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


_WRITE_LOCK = threading.Lock()


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """
    check_same_thread=False because FastAPI dispatches sync endpoints onto a
    threadpool, so a Session's connection will legitimately be touched from
    different threads across turns. Writes are serialised by _WRITE_LOCK and
    WAL keeps concurrent readers from blocking.

    Fine for a prototype. Phase 2 this becomes Postgres with a real pool —
    SQLite is not what you want once counsellors are reading dashboards while
    students are mid-session.
    """
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def _write(conn, sql: str, params: tuple) -> int:
    with _WRITE_LOCK:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount


def grant_consent(conn, pseudonym: str, session_id: str, scope: str) -> None:
    _write(conn, "INSERT OR IGNORE INTO consent VALUES (?,?,?,?)",
           (pseudonym, session_id, _now(), scope))


def has_consent(conn, pseudonym: str, session_id: str, scope: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM consent WHERE pseudonym=? AND session_id=? AND scope=?",
        (pseudonym, session_id, scope),
    )
    return cur.fetchone() is not None


def save_turn(conn, pseudonym: str, session_id: str, role: str, content: str) -> None:
    if not has_consent(conn, pseudonym, session_id, "store_conversation"):
        return  # incognito, or consent not given — silently do nothing
    _write(conn, "INSERT INTO turns VALUES (?,?,?,?,?)",
           (pseudonym, session_id, _now(), role, content))


def prior_turns(conn, pseudonym: str, exclude_session: str, limit: int = 20) -> list[tuple[str, str]]:
    """Longitudinal context from PREVIOUS sessions only — the current session's
    turns are already in the live history, which is what caused the earlier
    prototype to feed every message to the model twice."""
    cur = conn.execute(
        "SELECT role, content FROM turns WHERE pseudonym=? AND session_id!=? "
        "ORDER BY ts DESC LIMIT ?",
        (pseudonym, exclude_session, limit),
    )
    return list(reversed(cur.fetchall()))


def save_response(conn, pseudonym, session_id, instrument, item, response, confirmed=True) -> None:
    _write(conn, "INSERT OR REPLACE INTO instrument_responses VALUES (?,?,?,?,?,?,?)",
           (pseudonym, session_id, instrument, item, response, int(confirmed), _now()))


def save_score(conn, pseudonym, session_id, instrument, payload: dict) -> None:
    _write(conn, "INSERT INTO instrument_scores VALUES (?,?,?,?,?)",
           (pseudonym, session_id, instrument, _now(), json.dumps(payload)))


def score_history(conn, pseudonym: str, instrument: str = "dass21") -> list[dict]:
    cur = conn.execute(
        "SELECT ts, payload FROM instrument_scores WHERE pseudonym=? AND instrument=? ORDER BY ts",
        (pseudonym, instrument),
    )
    return [{"ts": ts, **json.loads(p)} for ts, p in cur.fetchall()]


def save_lifestyle(conn, pseudonym, session_id, slot, value, quote="") -> None:
    _write(conn, "INSERT OR REPLACE INTO lifestyle VALUES (?,?,?,?,?,?)",
           (pseudonym, session_id, slot, json.dumps(value), quote, _now()))


def log_risk(conn, pseudonym, session_id, level: int, reason: str) -> None:
    """Always written, Story Mode or not. A risk event is a safeguarding record,
    not conversational content. Incognito covers what was said, not that a
    safeguarding threshold was crossed. This must be disclosed to the student
    up front, in the privacy copy — not buried."""
    _write(conn, "INSERT INTO risk_events VALUES (?,?,?,?,?,0)",
           (pseudonym, session_id, _now(), level, reason))


def erase(conn, pseudonym: str) -> dict[str, int]:
    """Student-initiated erasure. Risk events survive — see note above."""
    counts = {}
    for table in ("turns", "instrument_responses", "instrument_scores", "lifestyle", "consent"):
        counts[table] = _write(conn, f"DELETE FROM {table} WHERE pseudonym=?", (pseudonym,))
    return counts


# ---------------------------------------------------------------------------
# Read side — everything the report needs, rebuilt from disk.
#
# The live Session object dies when the browser tab closes. These queries are
# what let a counsellor open the same session tomorrow. Nothing here invents a
# value: an empty table produces an empty section, which is the whole point.
# ---------------------------------------------------------------------------

def sessions_for(conn, pseudonym: str) -> list[dict]:
    """Every stored session for a pseudonym, newest first."""
    cur = conn.execute(
        """SELECT session_id,
                  MIN(ts) AS started,
                  MAX(ts) AS ended,
                  SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) AS user_turns
           FROM turns WHERE pseudonym=?
           GROUP BY session_id ORDER BY started DESC""",
        (pseudonym,),
    )
    return [
        {"session_id": s, "started": a, "ended": b, "user_turns": n}
        for s, a, b, n in cur.fetchall()
    ]


def turns_for(conn, pseudonym: str, session_id: str) -> list[dict]:
    cur = conn.execute(
        "SELECT ts, role, content FROM turns WHERE pseudonym=? AND session_id=? ORDER BY ts",
        (pseudonym, session_id),
    )
    return [{"ts": t, "role": r, "content": c} for t, r, c in cur.fetchall()]


def responses_for(conn, pseudonym: str, session_id: str,
                  instrument: str = "dass21") -> dict[int, int]:
    cur = conn.execute(
        """SELECT item, response FROM instrument_responses
           WHERE pseudonym=? AND session_id=? AND instrument=? AND confirmed=1
           ORDER BY item""",
        (pseudonym, session_id, instrument),
    )
    return {item: resp for item, resp in cur.fetchall()}


def lifestyle_for(conn, pseudonym: str, session_id: str) -> dict[str, tuple]:
    """Returns {slot: (value, quote)}. Quote is the student's own words, which
    is what a counsellor actually wants to see — not the parsed integer."""
    cur = conn.execute(
        "SELECT slot, value, quote FROM lifestyle WHERE pseudonym=? AND session_id=?",
        (pseudonym, session_id),
    )
    return {slot: (json.loads(val), quote or "") for slot, val, quote in cur.fetchall()}


def risk_for(conn, pseudonym: str, session_id: str | None = None) -> list[dict]:
    """session_id=None returns the pseudonym's full risk history, which is what
    the counsellor view wants — a pattern across sessions matters more than any
    single event."""
    if session_id is None:
        cur = conn.execute(
            "SELECT ts, session_id, level, reason, acknowledged FROM risk_events "
            "WHERE pseudonym=? ORDER BY ts DESC",
            (pseudonym,),
        )
    else:
        cur = conn.execute(
            "SELECT ts, session_id, level, reason, acknowledged FROM risk_events "
            "WHERE pseudonym=? AND session_id=? ORDER BY ts DESC",
            (pseudonym, session_id),
        )
    return [
        {"ts": t, "session_id": s, "level": lv, "reason": r, "acknowledged": bool(a)}
        for t, s, lv, r, a in cur.fetchall()
    ]


def acknowledge_risk(conn, pseudonym: str, session_id: str) -> int:
    """Counsellor marks a risk event as seen. Returns rows updated."""
    return _write(
        conn,
        "UPDATE risk_events SET acknowledged=1 WHERE pseudonym=? AND session_id=?",
        (pseudonym, session_id),
    )
