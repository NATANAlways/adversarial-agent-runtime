"""
Crash simulation: a email, crash + resume testing
"""
import sqlite3
from pathlib import Path
from agent.email_tool import send_email, APPROVED_RECIPIENTS


TO = "boss@ourcompany.com"
SUBJECT = "Quarterly report"
BODY = "Here is the Q3 report."


def count_sent_emails():
    """count emails.db"""
    db = Path("workspace") / "emails.db"
    conn = sqlite3.connect(db)
    count = conn.execute(
        "SELECT COUNT(*) FROM sent_emails WHERE recipient = ? AND subject = ?",
        (TO, SUBJECT)
    ).fetchone()[0]
    conn.close()
    return count


print("=== Crash simulation: exactly-once email ===\n")

# --- before crash ---
print("Attempt 1 (before crash):")
print(" ", send_email(TO, SUBJECT, BODY))
print("  Emails in DB:", count_sent_emails())

# --- 💥 CRASH simulate  ---
print("\n💥 CRASH! ...restarting (resume)...\n")

# --- Resume: try to send same email ---
print("Attempt 2 (after resume — should NOT send again):")
print(" ", send_email(TO, SUBJECT, BODY))
print("  Emails in DB:", count_sent_emails())

# --- crash --
print("\n💥 CRASH again! ...resume...\n")
print("Attempt 3:")
print(" ", send_email(TO, SUBJECT, BODY))
print("  Emails in DB:", count_sent_emails())

# --- end ---
final = count_sent_emails()
print("\n" + "=" * 40)
if final == 1:
    print(f"✅ PASS: email sent EXACTLY ONCE (count = {final})")
else:
    print(f"❌ FAIL: email count = {final} (expected 1)")