import sqlite3
conn = sqlite3.connect('job_agent.db')
c = conn.cursor()
# delete the 6 broken rows that have timestamps as status
c.execute("DELETE FROM seen_jobs WHERE status LIKE '2026-%'")
deleted = c.rowcount
conn.commit()
print(f'Cleaned {deleted} broken rows')
# show current state
for row in c.execute("SELECT status, COUNT(*) FROM seen_jobs GROUP BY status"):
    print(f'  {row[0]:<26} {row[1]}')
conn.close()
