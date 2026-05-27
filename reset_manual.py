import sqlite3
conn = sqlite3.connect('job_agent.db')
c = conn.cursor()

# reset manual apply jobs that have PDFs back to generated
c.execute("""
    UPDATE seen_jobs
    SET status = 'GENERATED_YES'
    WHERE status IN ('MANUAL_APPLY', 'FORM_FILLED')
""")
print(f'Reset {c.rowcount} jobs to GENERATED_YES')

# show current state
for row in c.execute("SELECT status, COUNT(*) FROM seen_jobs GROUP BY status ORDER BY status"):
    print(f'  {row[0]:<26} {row[1]}')

conn.commit()
conn.close()
