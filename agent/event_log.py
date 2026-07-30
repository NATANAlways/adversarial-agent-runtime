import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path("workspace") / "events.db"

def _get_db():
    """creating log database if the table is not already present."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            event_type TEXT,
            data TEXT,
            timestamp REAL
        )
    """)

    conn.commit()
    return conn

def log_event(run_id: str, event_type: str, data: dict):
    """
    logginf the events, only appending not removing
    """
    conn = _get_db()
    conn.execute(
        "INSERT INTO events (run_id, event_type, data, timestamp) VALUES (?, ?, ?, ?)",
        (run_id, event_type, json.dumps(data), time.time())
    )
    conn.commit()
    conn.close()

def get_events(run_id: str) -> list:
    """ for a run logging all the evnets in sequence"""
    conn = _get_db()
    rows = conn.execute(
        "SELECT seq, event_type, data, timestamp FROM events WHERE run_id = ? ORDER BY seq",
        (run_id,)
    ).fetchall()
    conn.close()

    events = []

    for seq, event_type, data, timestamp in rows:
        events.append({
            "seq": seq,
            "event_type": event_type,
            "data": json.loads(data),
            "timestamp": timestamp,
        })
    return events


def get_completed_tools(run_id: str) -> list:
    """
        taking tool_call + tool_result that fininshed in a run
    """
    events = get_events(run_id)

    completed = []
    pending_call = None

    for event in events:
        if event["event_type"] == "tool_call":
            pending_call = event["data"]
        elif event["event_type"] == "tool_result":
            if pending_call is not None:
                completed.append({
                    "tool": pending_call["tool"],
                    "args": pending_call["args"],
                    "result": event["data"]["result"],
                })
                pending_call = None
    return completed

def run_exsists(run_id: str) -> bool:
    """to check whther this run_id have events"""
    return len(get_events(run_id)) > 0