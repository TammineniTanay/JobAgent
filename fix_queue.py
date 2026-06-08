import sqlite3
conn = sqlite3.connect(r"C:\JobAgentData\job_agent.db")
c = conn.cursor()
c.execute("UPDATE seen_jobs SET status='TO_PROCESS' WHERE status='GENERATED_MAYBE'")
print(f"Fixed {c.rowcount} jobs -> TO_PROCESS")
conn.commit()
conn.close()
