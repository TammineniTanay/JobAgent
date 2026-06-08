"""
Fix job statuses so stage3 can apply to everything with a generated resume.
- TO_PROCESS jobs with PDFs → GENERATED_YES (auto-fill ATS forms)
- MANUAL_APPLY LinkedIn jobs with PDFs → GENERATED_YES (try Easy Apply)
"""
import sqlite3, os, re

DB = r"C:\JobAgentData\job_agent.db"
OUTPUT_DIR = "output"

def find_pdf(company, title):
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", f"{company}_{title}")[:55]
    if os.path.isdir(OUTPUT_DIR):
        for dd in sorted([d for d in os.listdir(OUTPUT_DIR)
                          if re.match(r"\d{4}-\d{2}-\d{2}", d)
                          and os.path.isdir(os.path.join(OUTPUT_DIR, d))], reverse=True):
            p = os.path.join(OUTPUT_DIR, dd, safe, "resume.pdf")
            if os.path.exists(p): return True
    return False

conn = sqlite3.connect(DB)
c = conn.cursor()

# Fix TO_PROCESS jobs that have PDFs
c.execute("SELECT jobpostingid, company, title, url FROM seen_jobs WHERE status='TO_PROCESS'")
to_process = c.fetchall()
fixed_tp = 0
for jid, company, title, url in to_process:
    if find_pdf(company, title):
        c.execute("UPDATE seen_jobs SET status='GENERATED_YES' WHERE jobpostingid=?", (jid,))
        print(f"  [TO_PROCESS→YES] {company} — {title[:45]}")
        fixed_tp += 1

# Fix MANUAL_APPLY LinkedIn jobs that have PDFs (try Easy Apply)
c.execute("SELECT jobpostingid, company, title, url FROM seen_jobs WHERE status='MANUAL_APPLY' AND url LIKE '%linkedin%'")
li_jobs = c.fetchall()
fixed_li = 0
for jid, company, title, url in li_jobs:
    if find_pdf(company, title):
        c.execute("UPDATE seen_jobs SET status='GENERATED_MAYBE' WHERE jobpostingid=?", (jid,))
        fixed_li += 1

conn.commit()
conn.close()

print(f"\n✅ Fixed {fixed_tp} TO_PROCESS → GENERATED_YES (non-LinkedIn ATS forms)")
print(f"✅ Fixed {fixed_li} LinkedIn MANUAL_APPLY → GENERATED_MAYBE (will try Easy Apply)")
print(f"\nNow run:  python stage3_apply.py")
