import sqlite3
conn = sqlite3.connect('job_agent.db')
c = conn.cursor()
try:
    c.execute("ALTER TABLE seen_jobs ADD COLUMN url_norm TEXT")
    c.execute("ALTER TABLE seen_jobs ADD COLUMN source TEXT DEFAULT 'excel'")
    c.execute("ALTER TABLE seen_jobs ADD COLUMN date_posted TEXT")
    conn.commit()
    print('Migration done')
except Exception as e:
    print(f'Already migrated or error: {e}')
conn.close()
