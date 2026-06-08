import sqlite3
conn = sqlite3.connect(r'C:\JobAgentData\job_agent.db')
c = conn.cursor()
c.execute('SELECT status, COUNT(*) FROM seen_jobs GROUP BY status ORDER BY COUNT(*) DESC')
print('=== Status breakdown ===')
for r in c.fetchall():
    print(f'  {r[0]:30s} {r[1]}')

c.execute("SELECT date_found, status, COUNT(*) FROM seen_jobs WHERE status NOT IN ('APPLIED','EXPIRED','MANUAL_NO_PDF') GROUP BY date_found, status ORDER BY date_found DESC LIMIT 20")
print()
print('=== Pending by date ===')
for r in c.fetchall():
    print(f'  {r[0]}  {r[1]:25s}  {r[2]}')

conn.close()
