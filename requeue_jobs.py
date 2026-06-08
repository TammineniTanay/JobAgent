"""
requeue_jobs.py
Shows all MANUAL_APPLY jobs and lets you mark good ones as GENERATED_MAYBE
so stage2 will generate resumes and stage3 will apply to them.
"""
import sqlite3

DB = r"C:\JobAgentData\job_agent.db"

conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute("""
    SELECT jobpostingid, company, title, url, date_found
    FROM seen_jobs
    WHERE status = 'MANUAL_APPLY'
    ORDER BY date_found DESC
""")
jobs = c.fetchall()

if not jobs:
    print("No MANUAL_APPLY jobs in queue.")
    conn.close()
    exit()

print(f"\n{'='*70}")
print(f"  {len(jobs)} MANUAL_APPLY jobs — mark good ones for resume generation")
print(f"  Commands:  y = yes (queue it)  |  s = skip  |  q = quit and save")
print(f"{'='*70}\n")

to_requeue = []

for i, (jid, company, title, url, date) in enumerate(jobs, 1):
    ats = "?"
    u = url.lower()
    for name, pat in [
        ("LinkedIn","linkedin.com"),("Greenhouse","greenhouse.io"),("Workable","workable"),
        ("Lever","lever.co"),("Ashby","ashby"),("SmartRecruiters","smartrecruiters"),
        ("Paylocity","paylocity"),("Workday","workday"),("Greenhouse","gh_jid"),
        ("Paycor","paycor"),("UltiPro","ultipro"),("BambooHR","bamboohr"),
        ("iCIMS","icims"),("Taleo","taleo"),
    ]:
        if pat in u:
            ats = name
            break

    date_s = date[:10] if date else "?"
    print(f"[{i}/{len(jobs)}]  {company}")
    print(f"       {title}")
    print(f"       ATS: {ats}  |  {date_s}")
    print(f"       {url[:80]}")

    choice = input("  [y=queue / s=skip / q=quit] > ").strip().lower()
    print()

    if choice == "q":
        break
    elif choice == "y":
        to_requeue.append(jid)

if to_requeue:
    c.executemany(
        "UPDATE seen_jobs SET status='TO_PROCESS' WHERE jobpostingid=?",
        [(jid,) for jid in to_requeue]
    )
    conn.commit()
    print(f"\n✅ {len(to_requeue)} jobs re-queued as TO_PROCESS")
    print(f"\nNow run:")
    print(f"  python stage2_generate.py   ← generates tailored resumes")
    print(f"  python stage3_apply.py      ← auto-applies with those resumes")
else:
    print("\nNo jobs re-queued.")

conn.close()
