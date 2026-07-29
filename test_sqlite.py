import sqlite3

conn = sqlite3.connect("test.db")

conn.execute("""
             
        CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY,
        recipient TEXT,
        subject TEXT
    )
    """)

conn.execute(
    "INSERT INTO emails (recipient, subject) VALUES (?, ?)",
    ("bob@example.com", "Hello Bob")
)

conn.commit()

rows = conn.execute("SELECT * FROM emails").fetchall()
print("Database")
for row in rows:
    print(" ", row)

conn.close()