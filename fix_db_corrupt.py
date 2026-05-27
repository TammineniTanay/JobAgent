import sqlite3
import os
import shutil

# backup the corrupted file first
if os.path.exists('job_agent.db'):
    shutil.copy('job_agent.db', 'job_agent.db.corrupted')
    print('Backed up corrupted DB')

# try to recover data from corrupted DB
recovered = []
try:
    conn_old = sqlite3.connect('job_agent.db')
    conn_old.execute("PRAGMA integrity_check")
    rows = conn_old.execute("SELECT * FROM seen_jobs").fetchall()
    recovered = rows
    conn_old.close()
    print(f'Recovered {len(recovered)} rows')
except Exception as e:
    print(f'Could not recover data: {e}')
    print('Starting fresh.')

# delete corrupted file
os.remove('job_agent.db')
print('Deleted corrupted DB')

# create fresh DB
conn_new = sqlite3.connect('job_agent.db')
c = conn_new.cursor()
c.execute('''
    CREATE TABLE seen_jobs (
        jobpostingid  TEXT PRIMARY KEY,
        url           TEXT,
        url_norm      TEXT,
        company       TEXT,
        title         TEXT,
        date_found    TEXT,
        status        TEXT,
        jd_text       TEXT,
        source        TEXT DEFAULT 'excel',
        date_posted   TEXT
    )
''')

if recovered:
    # re-insert recovered rows
    for row in recovered:
        try:
            # pad row to 10 columns if shorter (old schema)
            padded = list(row) + [None] * (10 - len(row))
            c.execute(
                'INSERT OR IGNORE INTO seen_jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                padded[:10]
            )
        except Exception:
            pass
    conn_new.commit()
    print(f'Restored {len(recovered)} rows to fresh DB')

# show summary
c.execute("SELECT status, COUNT(*) FROM seen_jobs GROUP BY status")
for row in c.fetchall():
    print(f'  {row[0]:<26} {row[1]}')

conn_new.close()
print('Done. Run: python run_pipeline.py')
