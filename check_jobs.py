import sqlite3
conn = sqlite3.connect('job_agent.db')
c = conn.cursor()
print('\n=== READY TO APPLY ===')
c.execute("SELECT company, title, url, status FROM seen_jobs WHERE status IN ('GENERATED_YES','GENERATED_MAYBE') ORDER BY status, company")
for co, ti, url, st in c.fetchall():
    print(f'[{st}] [{co}] {ti}')
    print(f'  {url}')
print('\n=== MANUAL QUEUE ===')
c.execute("SELECT company, title, url FROM seen_jobs WHERE status IN ('MANUAL_APPLY','MANUAL_NO_PDF')")
for co, ti, url in c.fetchall():
    print(f'[{co}] {ti}')
    print(f'  {url}')
conn.close()
