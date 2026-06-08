"""Show jobs that have resume PDFs generated but aren't applied yet."""
import sqlite3, os, re

DB = r"C:\JobAgentData\job_agent.db"
OUTPUT_DIR = "output"

conn = sqlite3.connect(DB)
c = conn.cursor()

# All non-applied jobs
c.execute("""SELECT jobpostingid, company, title, url, status, date_found
             FROM seen_jobs
             WHERE status NOT IN ('APPLIED','EXPIRED','SKIPPED_NO')
             ORDER BY date_found DESC""")
jobs = c.fetchall()
conn.close()

print(f"\n{'='*65}")
print(f"  Jobs with resume PDFs ready (can be applied to now)")
print(f"{'='*65}")

has_pdf = []
no_pdf = []

for job_id, company, title, url, status, date in jobs:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", f"{company}_{title}")[:55]
    pdf = None
    if os.path.isdir(OUTPUT_DIR):
        for dd in sorted([d for d in os.listdir(OUTPUT_DIR)
                          if re.match(r"\d{4}-\d{2}-\d{2}", d)
                          and os.path.isdir(os.path.join(OUTPUT_DIR, d))], reverse=True):
            p = os.path.join(OUTPUT_DIR, dd, safe, "resume.pdf")
            if os.path.exists(p):
                pdf = p; break
    if pdf:
        has_pdf.append((company, title, url, status, pdf))
    else:
        no_pdf.append((company, title, status))

print(f"\n  ✅ {len(has_pdf)} jobs WITH resume PDF (ready to apply):")
for company, title, url, status, pdf in has_pdf:
    ats = "?"
    u = url.lower()
    for name, pat in [("Workable","workable"),("Greenhouse","greenhouse"),("Lever","lever"),
                      ("Ashby","ashby"),("Paylocity","paylocity"),("Personio","personio"),
                      ("SmartRecruiters","smartrecruiters"),("Paycor","paycor"),
                      ("UltiPro","ultipro"),("LinkedIn","linkedin"),("BambooHR","bamboohr")]:
        if pat in u: ats = name; break
    print(f"    [{status}] {company} — {title[:40]} ({ats})")

print(f"\n  ❌ {len(no_pdf)} jobs WITHOUT resume (need stage2):")
for company, title, status in no_pdf[:10]:
    print(f"    [{status}] {company} — {title[:45]}")
if len(no_pdf) > 10:
    print(f"    ... and {len(no_pdf)-10} more")

print()
