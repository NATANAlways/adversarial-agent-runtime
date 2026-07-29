import sqlite3
import hashlib
from pathlib import Path

DB_PATH = Path("workspace") / "emails.db"

APPROVED_RECIPIENTS = {
    "boss@ourcompany.com",
    "team@ourcompany.com",
}

def _get_db():
    """create table in db"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS sent_emails (
            idempotency_key TEXT PRIMARY KEY,
            recipient TEXT,
            subject TEXT,
            body TEXT
        )
    """)
    
    conn.commit()
    return conn

def _make_key(to: str, subject: str, body: str) -> str:
    """
    unique id creating
    """
    combined = f"{to} | {subject} | {body}"
    return hashlib.sha256(combined.encode()).hexdigest()

def send_email(to: str, subject: str, body: str) -> str:
    if to not in APPROVED_RECIPIENTS:
        return f"REFUSED: '{to}' is not an approved recipient. Approved: {sorted(APPROVED_RECIPIENTS)}"
    
    """
    Send email only once 
    """
    key = _make_key(to, subject, body)
    conn = _get_db()

    existing = conn.execute(
        "SELECT idempotency_key FROM sent_emails WHERE idempotency_key = ?",
        (key,)
    ).fetchone()

    if existing is not None:
        conn.close()
        return f"SKIPPED: this email was already sent (key {key[:12]}...)"

    conn.execute(
        "INSERT INTO sent_emails (idempotency_key, recipient, subject, body) VALUES (?, ?, ?, ?)",
        (key, to, subject, body)
    )
    conn.commit()   
    conn.close()
    return f"SENT: email to {to} (key {key[:12]}...)"
