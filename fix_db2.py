import sqlite3
conn = sqlite3.connect('job_agent.db')
c = conn.cursor()
cols = [row[1] for row in c.execute("PRAGMA table_info(seen_jobs)")]
print("Column order:", cols)
c.execute("DELETE FROM seen_jobs WHERE status LIKE '2026-%' OR status LIKE '2025-%'")
print(f"Deleted {c.rowcount} broken rows")
for row in c.execute("SELECT status, COUNT(*) FROM seen_jobs GROUP BY status"):
    print(f"  {row[0]:<30} {row[1]}")
conn.commit()
conn.close()
