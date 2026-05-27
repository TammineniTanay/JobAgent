import sqlite3
c = sqlite3.connect('job_agent.db')
c.execute("UPDATE seen_jobs SET status='TO_PROCESS' WHERE status NOT IN ('GENERATED_YES','GENERATED_MAYBE','SKIPPED_NO')")
c.commit()
print('Reset done')
c.close()
