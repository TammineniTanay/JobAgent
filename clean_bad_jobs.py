"""
clean_bad_jobs.py
Deletes all jobs with HTML company names or company homepage URLs.
Applies to ALL sources (Excel + GitHub) — homepage URLs are useless regardless of source.
Run this once before running the pipeline again.
"""
import sqlite3
import re
from urllib.parse import urlparse

DB_PATH = r"C:\JobAgentData\job_agent.db"

ATS_MARKERS = [
    "greenhouse.io", "lever.co", "workday", "myworkdayjobs", "ashbyhq",
    "smartrecruiters", "jobvite", "icims", "taleo",
    "paylocity", "workable", "rippling", "bamboohr",
    "personio", "paycor", "oraclecloud", "ultipro", "adp.com",
    "successfactors", "dayforcehcm", "linkedin.com",
]
JOB_PATHS = ["/jobs/", "/careers/", "/job/", "/apply", "/posting/",
             "/position/", "/opening/", "/vacancy/"]

def is_real_job_url(url):
    if not url or not url.startswith("http"):
        return False
    u = url.lower()
    if any(ats in u for ats in ATS_MARKERS):
        return True
    if any(p in u for p in JOB_PATHS):
        if "github.com" not in u:
            return True
    try:
        parsed = urlparse(url)
        if not parsed.path.strip("/"):
            return False  # bare homepage
    except Exception:
        pass
    return True

conn = sqlite3.connect(DB_PATH)
c    = conn.cursor()

# 1. delete jobs with HTML in company name (any source)
c.execute("""
    DELETE FROM seen_jobs
    WHERE company LIKE '%<a href%'
       OR company LIKE '%<strong%'
       OR company LIKE '%href=%'
       OR company LIKE '%&lt;%'
""")
html_deleted = c.rowcount
print(f"Deleted {html_deleted} jobs with HTML company names")

# 2. delete ALL jobs (any source) where URL is a bare company homepage
c.execute("SELECT jobpostingid, url FROM seen_jobs")
rows = c.fetchall()
url_deleted = 0
for jid, url in rows:
    if not is_real_job_url(url or ""):
        c.execute("DELETE FROM seen_jobs WHERE jobpostingid=?", (jid,))
        url_deleted += 1

print(f"Deleted {url_deleted} jobs with company homepage URLs (all sources)")

conn.commit()

# 3. show what's left
print("\n--- Current DB state ---")
c.execute("SELECT status, COUNT(*) FROM seen_jobs GROUP BY status ORDER BY status")
for row in c.fetchall():
    print(f"  {row[0]:<26} {row[1]}")

print("\n--- Remaining GENERATED jobs (ready to apply) ---")
c.execute("""
    SELECT company, title, url FROM seen_jobs
    WHERE status IN ('GENERATED_YES','GENERATED_MAYBE','MANUAL_APPLY')
    ORDER BY status, date_found DESC
    LIMIT 20
""")
for co, ti, url in c.fetchall():
    print(f"  [{co}] {ti}")
    print(f"  {url[:80]}")

conn.close()
print("\nDone. Now run: python run_pipeline.py")
