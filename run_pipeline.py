"""
run_pipeline.py
One command runs everything automatically: Stage 1 → Stage 2 → Stage 3 → Tracker.

Usage:
    python run_pipeline.py                 ← full pipeline (recommended daily use)
    python run_pipeline.py --stage 1       ← only ingest
    python run_pipeline.py --stage 2       ← only generate docs
    python run_pipeline.py --stage 3       ← only apply
    python run_pipeline.py --track         ← regenerate tracker dashboard
    python run_pipeline.py --remind        ← print follow-up reminders
    python run_pipeline.py --reset         ← reset FAILED jobs to TO_PROCESS
"""

import sys
import os
import sqlite3
import argparse
import subprocess
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS — edit once
# ─────────────────────────────────────────────────────────────────────────────

EXCEL_FILE   = "daily_jobs.xlsx"
DB_PATH = r"C:\JobAgentData\job_agent.db"
GITHUB_TOKEN = None    # optional — github.com/settings/tokens (no scopes needed)

# Discord webhook — free, takes 5 minutes to set up
# Server Settings → Integrations → Webhooks → New Webhook → Copy URL
DISCORD_WEBHOOK = ""   # paste URL here or leave blank

# Auto-push output to Git after every run
GIT_AUTO_PUSH = False  # flip to True after: git init + git remote add origin <url>

# ─────────────────────────────────────────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────────────────────────────────────────

def discord_notify(message):
    if not DISCORD_WEBHOOK:
        return
    try:
        import requests
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"  Discord failed: {e}")


def build_discord_message(s1_count, s2_results, s3_results, manual_jobs, elapsed_mins):
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"🤖 **Job Pipeline Complete** — {now}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📥 Stage 1: **{s1_count}** new jobs queued",
    ]
    if s2_results:
        yes   = s2_results.get("YES", 0)
        maybe = s2_results.get("MAYBE", 0)
        no    = s2_results.get("NO", 0)
        fail  = s2_results.get("FAILED", 0)
        lines.append(f"📄 Stage 2: YES **{yes}** | MAYBE **{maybe}** | NO {no} | Failed {fail}")
    if s3_results:
        auto = s3_results.get("applied_auto", 0)
        man  = s3_results.get("filled_manual", 0)
        mq   = s3_results.get("manual_queue", 0)
        lines.append(f"✅ Stage 3: Auto-applied **{auto}** | Filled {man} | Manual queue {mq}")
    lines.append(f"⏱ Total: {elapsed_mins:.1f} min")
    if manual_jobs:
        lines.append(f"\n📋 **Manual Queue ({len(manual_jobs)}):**")
        for co, ti, url in manual_jobs[:6]:
            lines.append(f"• [{co}] {ti}")
        if len(manual_jobs) > 6:
            lines.append(f"• ... and {len(manual_jobs)-6} more")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# GIT AUTO-PUSH
# ─────────────────────────────────────────────────────────────────────────────

def git_push():
    if not GIT_AUTO_PUSH:
        return
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(["git", "add", "output/"],
                       check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"pipeline run {now_str}"],
                       check=True, capture_output=True)
        subprocess.run(["git", "push"],
                       check=True, capture_output=True)
        print("  Git: output pushed.")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode().strip()[:80] if e.stderr else "no changes"
        print(f"  Git push skipped: {stderr}")
    except FileNotFoundError:
        print("  Git not found — skipping.")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def banner(text):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'─' * 55}")
    print(f"  {text}  [{now}]")
    print(f"{'─' * 55}")


def db_summary():
    if not os.path.exists(DB_PATH):
        return
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    # only show real statuses, not timestamp artefacts
    c.execute("""
        SELECT status, COUNT(*) FROM seen_jobs
        WHERE status NOT LIKE '2026-%' AND status NOT LIKE '2025-%'
        GROUP BY status ORDER BY status
    """)
    rows = c.fetchall()
    conn.close()
    if rows:
        print("\n  Database summary:")
        for status, count in rows:
            print(f"    {status:<26} {count}")


def get_manual_jobs():
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        SELECT company, title, url FROM seen_jobs
        WHERE status IN ('MANUAL_APPLY','MANUAL_NO_PDF','FORM_FILLED')
        ORDER BY company
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def reset_failed():
    if not os.path.exists(DB_PATH):
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE seen_jobs SET status='TO_PROCESS' WHERE status='FAILED'")
    # also clean up timestamp-status artefacts
    conn.execute("DELETE FROM seen_jobs WHERE status LIKE '2026-%' OR status LIKE '2025-%'")
    conn.commit()
    conn.close()
    print("  Failed jobs reset. Timestamp artefacts cleaned.")


def check_deps():
    missing = []
    for pkg in ["pandas", "openpyxl", "requests"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print(f"Install: pip install {' '.join(missing)}")
        return False
    return True

# ─────────────────────────────────────────────────────────────────────────────
# TRACKER — called directly to avoid argparse conflicts
# ─────────────────────────────────────────────────────────────────────────────

def run_tracker():
    banner("TRACKER — Generating Dashboard")
    try:
        from tracker import load_jobs, generate_html, print_reminders
        jobs = load_jobs(DB_PATH)
        if jobs:
            html = generate_html(jobs)
            out  = "tracker.html"
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  Dashboard: {os.path.abspath(out)}")
            print(f"  Open:      file:///{os.path.abspath(out).replace(os.sep, '/')}")
            print_reminders(jobs)
        else:
            print("  No jobs yet.")
    except Exception as e:
        print(f"  Tracker error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# STAGE RUNNERS
# ─────────────────────────────────────────────────────────────────────────────

def run_stage1():
    banner("STAGE 1 — Ingest + Filter + JD Scrape")
    from stage1_ingest import main as s1
    jobs = s1(excel_path=EXCEL_FILE, github_token=GITHUB_TOKEN, db_path=DB_PATH)
    print(f"\n  {len(jobs)} new jobs queued.")
    return len(jobs)


def run_stage2():
    banner("STAGE 2 — Resume + Cover Letter Generation")
    from stage2_generate import main as s2
    results = s2(db_path=DB_PATH)
    return results or {}


def run_stage3():
    banner("STAGE 3 — Application Submission")
    from stage3_apply import main as s3
    results = s3(db_path=DB_PATH)
    return results or {}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Job Application Pipeline")
    parser.add_argument("--stage",  type=int, choices=[1, 2, 3], default=None)
    parser.add_argument("--track",  action="store_true")
    parser.add_argument("--remind", action="store_true")
    parser.add_argument("--reset",  action="store_true")
    args = parser.parse_args()

    if not check_deps():
        sys.exit(1)

    start = datetime.now()
    print(f"\n{'=' * 55}")
    print(f"  Job Application Pipeline")
    print(f"  {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Excel:    {EXCEL_FILE}")
    print(f"  Discord:  {'enabled' if DISCORD_WEBHOOK else 'disabled'}")
    print(f"  Git push: {'enabled' if GIT_AUTO_PUSH else 'disabled'}")
    print(f"{'=' * 55}")

    # ── special commands ──────────────────────────────────────────────────────
    if args.reset:
        reset_failed()
        db_summary()
        return

    if args.track:
        run_tracker()
        return

    if args.remind:
        try:
            from tracker import load_jobs, print_reminders
            print_reminders(load_jobs(DB_PATH))
        except Exception as e:
            print(f"  Error: {e}")
        return

    # ── stage runners ─────────────────────────────────────────────────────────
    s1_count   = 0
    s2_results = {}
    s3_results = {}

    if args.stage == 1:
        s1_count = run_stage1()

    elif args.stage == 2:
        s2_results = run_stage2()

    elif args.stage == 3:
        s3_results = run_stage3()

    else:
        # ── FULL PIPELINE — one command does everything ───────────────────────
        s1_count = run_stage1()

        if s1_count == 0:
            print("\n  No new jobs today — Stage 2 and 3 skipped.")
        else:
            s2_results = run_stage2()
            s3_results = run_stage3()

    # ── post-run ──────────────────────────────────────────────────────────────
    run_tracker()
    git_push()
    db_summary()

    elapsed     = (datetime.now() - start).total_seconds() / 60
    manual_jobs = get_manual_jobs()

    discord_notify(build_discord_message(
        s1_count, s2_results, s3_results, manual_jobs, elapsed
    ))

    mins, secs = divmod(int((datetime.now() - start).total_seconds()), 60)
    print(f"\n  Total time: {mins}m {secs}s")
    print(f"  Output:    {os.path.abspath('output')}/")
    print(f"  Tracker:   {os.path.abspath('tracker.html')}")
    if manual_jobs:
        print(f"\n  {len(manual_jobs)} jobs need manual apply — see tracker.html")


if __name__ == "__main__":
    main()