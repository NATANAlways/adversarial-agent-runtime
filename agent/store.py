"""SQLite durability layer. This module is the entire R2 story: an
append-only event log plus an idempotency-keyed tool_calls table, with
send_email's "irreversible side effect" recorded in the *same* transaction
as the record of having sent it -- so there is no reachable state where an
email both went out and the log doesn't know about it, or vice versa.

Every write goes through `transaction()` (BEGIN IMMEDIATE ... COMMIT/ROLLBACK)
so a kill -9 at any point either lands a fully-committed change or nothing at
all -- never a half-written row.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  task TEXT NOT NULL,
  scenario TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','failed','terminated')),
  termination_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq INTEGER NOT NULL,
  step INTEGER NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);

CREATE TABLE IF NOT EXISTS tool_calls (
  idempotency_key TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  step INTEGER NOT NULL,
  block_index INTEGER NOT NULL,
  tool_name TEXT NOT NULL,
  input_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','completed','error')),
  result_json TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id);

CREATE TABLE IF NOT EXISTS sent_emails (
  idempotency_key TEXT PRIMARY KEY REFERENCES tool_calls(idempotency_key),
  run_id TEXT NOT NULL,
  to_addr TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  sent_at TEXT NOT NULL
);
"""


def get_connection(db_path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or config.DB_PATH), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")  # fsync before commit returns -- survives kill -9
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def idempotency_key(run_id: str, step: int, block_index: int, tool_name: str, input_obj: Any) -> str:
    """Deliberately excludes the model's own tool_use.id: mockllm's S9
    scenario reuses that id across different steps for different calls, so
    keying on it would misattribute results. The agent's own (step,
    block_index) is what's actually unique per call."""
    payload = f"{run_id}|{step}|{block_index}|{tool_name}|{canonical_json(input_obj)}"
    return hashlib.sha256(payload.encode()).hexdigest()


# -- runs ---------------------------------------------------------------
def create_run(conn: sqlite3.Connection, run_id: str, task: str, scenario: str) -> None:
    with transaction(conn):
        ts = now_iso()
        conn.execute(
            "INSERT INTO runs(run_id, task, scenario, status, created_at, updated_at) "
            "VALUES (?,?,?, 'running', ?, ?)",
            (run_id, task, scenario, ts, ts),
        )


def get_run(conn: sqlite3.Connection, run_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_run_status(
    conn: sqlite3.Connection, run_id: str, status: str, termination_reason: Optional[str] = None
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE runs SET status=?, termination_reason=?, updated_at=? WHERE run_id=?",
            (status, termination_reason, now_iso(), run_id),
        )


# -- events ---------------------------------------------------------------
def _next_seq(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE run_id=?", (run_id,)).fetchone()
    return row[0] + 1


def _insert_event(conn: sqlite3.Connection, run_id: str, step: int, type_: str, payload: Any) -> int:
    """Caller must already be inside a transaction() block."""
    seq = _next_seq(conn, run_id)
    conn.execute(
        "INSERT INTO events(run_id, seq, step, type, payload_json, created_at) VALUES (?,?,?,?,?,?)",
        (run_id, seq, step, type_, json.dumps(payload, default=str), now_iso()),
    )
    conn.execute("UPDATE runs SET updated_at=? WHERE run_id=?", (now_iso(), run_id))
    return seq


def append_event(conn: sqlite3.Connection, run_id: str, step: int, type_: str, payload: Any) -> int:
    with transaction(conn):
        return _insert_event(conn, run_id, step, type_, payload)


def load_events(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM events WHERE run_id=? ORDER BY seq ASC", (run_id,)
    ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["payload"] = json.loads(event["payload_json"])
        events.append(event)
    return events


# -- tool calls ---------------------------------------------------------------
def get_tool_call(conn: sqlite3.Connection, key: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM tool_calls WHERE idempotency_key=?", (key,)).fetchone()
    if not row:
        return None
    call = dict(row)
    call["input"] = json.loads(call["input_json"])
    call["result"] = json.loads(call["result_json"]) if call["result_json"] else None
    return call


def begin_tool_call(
    conn: sqlite3.Connection,
    key: str,
    run_id: str,
    step: int,
    block_index: int,
    tool_name: str,
    input_obj: Any,
) -> tuple[bool, dict]:
    """Write-ahead record: INSERT OR IGNORE the pending row + log the intent,
    atomically. Returns (is_new, current_row). If is_new is False, this exact
    call was already seen before (e.g. we're resuming) -- the caller must NOT
    dispatch again, just look at the row's status."""
    with transaction(conn):
        cur = conn.execute(
            "INSERT OR IGNORE INTO tool_calls"
            "(idempotency_key, run_id, step, block_index, tool_name, input_json, status, created_at) "
            "VALUES (?,?,?,?,?,?, 'pending', ?)",
            (key, run_id, step, block_index, tool_name, canonical_json(input_obj), now_iso()),
        )
        is_new = cur.rowcount == 1
        if is_new:
            _insert_event(
                conn,
                run_id,
                step,
                "tool_call_intent",
                {
                    "idempotency_key": key,
                    "block_index": block_index,
                    "tool_name": tool_name,
                    "input": input_obj,
                },
            )
    return is_new, get_tool_call(conn, key)


def complete_tool_call(
    conn: sqlite3.Connection, key: str, run_id: str, step: int, status: str, result_obj: Any
) -> None:
    """For every tool EXCEPT send_email. send_email uses
    dispatch_send_email_atomic instead, which folds the side effect itself
    into the same transaction."""
    with transaction(conn):
        conn.execute(
            "UPDATE tool_calls SET status=?, result_json=?, completed_at=? WHERE idempotency_key=?",
            (status, json.dumps(result_obj, default=str), now_iso(), key),
        )
        _insert_event(
            conn, run_id, step, "tool_call_result",
            {"idempotency_key": key, "status": status, "result": result_obj},
        )


def dispatch_send_email_atomic(
    conn: sqlite3.Connection,
    key: str,
    run_id: str,
    step: int,
    to_addr: str,
    subject: str,
    body: str,
    result_obj: Any,
) -> None:
    """The exactly-once mechanism: marking the tool_call completed, recording
    the send in sent_emails, and logging the event all happen in one
    transaction. Either all three land, or none do -- there is no reachable
    state where the email 'sent' but the log doesn't know, or the log says
    'completed' but sent_emails has no row. sent_emails.idempotency_key is a
    PRIMARY KEY, so even a logic bug that calls this twice for the same key
    fails the transaction rather than sending twice."""
    with transaction(conn):
        conn.execute(
            "UPDATE tool_calls SET status='completed', result_json=?, completed_at=? "
            "WHERE idempotency_key=?",
            (json.dumps(result_obj, default=str), now_iso(), key),
        )
        conn.execute(
            "INSERT INTO sent_emails(idempotency_key, run_id, to_addr, subject, body, sent_at) "
            "VALUES (?,?,?,?,?,?)",
            (key, run_id, to_addr, subject, body, now_iso()),
        )
        _insert_event(
            conn, run_id, step, "tool_call_result",
            {"idempotency_key": key, "status": "completed", "result": result_obj},
        )


def list_sent_emails(conn: sqlite3.Connection, run_id: Optional[str] = None) -> list[dict]:
    if run_id:
        rows = conn.execute(
            "SELECT * FROM sent_emails WHERE run_id=? ORDER BY sent_at", (run_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sent_emails ORDER BY sent_at").fetchall()
    return [dict(r) for r in rows]
