"""
tracker.py
Generates a colour-coded HTML dashboard grouped by date.
Today's jobs appear at the top, older ones below.
Also prints follow-up reminders for applications older than 7 days.

Usage:
    python tracker.py              → generates tracker.html + prints reminders
    python tracker.py --remind     → only print follow-up reminders
"""

import sqlite3
import os
import argparse
from datetime import datetime, timedelta

DB_PATH       = "job_agent.db"
HTML_OUT      = "tracker.html"
FOLLOWUP_DAYS = 7

STATUS_META = {
    "APPLIED":          {"color": "#22c55e", "label": "Applied ✓",       "order": 0},
    "FORM_FILLED":      {"color": "#86efac", "label": "Form Filled",      "order": 1},
    "GENERATED_YES":    {"color": "#3b82f6", "label": "Ready (YES)",      "order": 2},
    "GENERATED_MAYBE":  {"color": "#93c5fd", "label": "Ready (MAYBE)",    "order": 3},
    "MANUAL_APPLY":     {"color": "#f97316", "label": "Manual Apply",     "order": 4},
    "MANUAL_NO_PDF":    {"color": "#fb923c", "label": "No PDF",           "order": 5},
    "TO_PROCESS":       {"color": "#facc15", "label": "Queued",           "order": 6},
    "SKIPPED_NO":       {"color": "#94a3b8", "label": "Skipped",          "order": 7},
    "FAILED":           {"color": "#f87171", "label": "Failed",           "order": 8},
    "FAILED_APPLY":     {"color": "#ef4444", "label": "Apply Failed",     "order": 9},
}

def load_jobs(db_path):
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    c    = conn.cursor()
    try:
        c.execute("""
            SELECT jobpostingid, company, title, url, status, date_found, source
            FROM seen_jobs
            WHERE status NOT LIKE '2026-%' AND status NOT LIKE '2025-%'
            ORDER BY date_found DESC
        """)
        rows = c.fetchall()
    except Exception:
        rows = []
    conn.close()
    return rows

def status_counts(jobs):
    counts = {}
    for row in jobs:
        s = row[4]
        counts[s] = counts.get(s, 0) + 1
    return counts

def follow_up_reminders(jobs):
    reminders = []
    cutoff    = datetime.now() - timedelta(days=FOLLOWUP_DAYS)
    for job_id, company, title, url, status, date_found, source in jobs:
        if status != "APPLIED":
            continue
        try:
            applied_dt = datetime.fromisoformat(date_found)
            if applied_dt < cutoff:
                days_ago = (datetime.now() - applied_dt).days
                reminders.append((company, title, url, days_ago))
        except Exception:
            pass
    return sorted(reminders, key=lambda x: -x[3])

def group_jobs_by_date(jobs):
    """Group jobs by their date_found date string (YYYY-MM-DD)."""
    groups = {}
    for row in jobs:
        date_found = row[5]
        try:
            day = datetime.fromisoformat(date_found).strftime("%Y-%m-%d")
        except Exception:
            day = "Unknown Date"
        if day not in groups:
            groups[day] = []
        groups[day].append(row)
    # sort groups newest first
    return dict(sorted(groups.items(), reverse=True))

def generate_html(jobs):
    counts    = status_counts(jobs)
    total     = len(jobs)
    today_str = datetime.now().strftime("%Y-%m-%d")
    applied   = counts.get("APPLIED", 0) + counts.get("FORM_FILLED", 0)
    ready     = counts.get("GENERATED_YES", 0) + counts.get("GENERATED_MAYBE", 0)
    manual    = counts.get("MANUAL_APPLY", 0) + counts.get("MANUAL_NO_PDF", 0)
    queued    = counts.get("TO_PROCESS", 0)
    reminders = follow_up_reminders(jobs)
    grouped   = group_jobs_by_date(jobs)
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M")

    # build date-grouped table HTML
    table_html = ""
    for day, day_jobs in grouped.items():
        is_today  = day == today_str
        label     = "Today" if is_today else day
        highlight = "#1d3048" if is_today else "#1e293b"
        border    = "border-left: 3px solid #3b82f6;" if is_today else ""
        day_count = len(day_jobs)

        table_html += f"""
        <tr>
          <td colspan="5" style="padding:10px 12px 4px;background:{highlight};
              font-size:13px;font-weight:700;color:{'#60a5fa' if is_today else '#94a3b8'};
              {border}">
            {'📅 ' if is_today else ''}{label}
            <span style="font-weight:400;color:#64748b;font-size:12px">
              &nbsp;({day_count} job{'s' if day_count != 1 else ''})
            </span>
          </td>
        </tr>"""

        # sort within the day: YES first, MAYBE, then others
        day_jobs_sorted = sorted(
            day_jobs,
            key=lambda r: STATUS_META.get(r[4], {"order": 99})["order"]
        )

        for job_id, company, title, url, status, date_found, source in day_jobs_sorted:
            meta      = STATUS_META.get(status, {"color": "#e2e8f0", "label": status})
            badge     = (f'<span style="background:{meta["color"]};color:#1e293b;'
                         f'padding:2px 8px;border-radius:12px;font-size:12px;'
                         f'font-weight:600">{meta["label"]}</span>')
            src_icon  = "🐙" if source == "github" else "📊"
            time_fmt  = ""
            try:
                time_fmt = datetime.fromisoformat(date_found).strftime("%H:%M")
            except Exception:
                pass

            table_html += f"""
        <tr style="{'background:#162032' if is_today else ''}">
          <td style="padding:7px 12px">{src_icon} <b>{company}</b></td>
          <td style="padding:7px 12px;color:#cbd5e1">{title}</td>
          <td style="padding:7px 12px">{badge}</td>
          <td style="padding:7px 12px;font-size:12px;color:#64748b">{time_fmt}</td>
          <td style="padding:7px 12px">
            <a href="{url}" target="_blank"
               style="color:#3b82f6;text-decoration:none;font-size:13px">Open ↗</a>
          </td>
        </tr>"""

    # reminder block
    reminder_html = ""
    if reminders:
        items = ""
        for co, ti, u, days in reminders:
            items += (f'<li style="margin:6px 0"><b>{co}</b> — {ti} '
                      f'<span style="color:#94a3b8">({days}d ago)</span> '
                      f'<a href="{u}" style="color:#f97316" target="_blank">↗</a></li>')
        reminder_html = f"""
        <div style="background:#1e293b;border:1px solid #f97316;border-radius:8px;
                    padding:16px;margin-bottom:24px">
          <h3 style="margin:0 0 12px;color:#f97316">⏰ Follow-Up Reminders ({len(reminders)})</h3>
          <ul style="margin:0;padding-left:20px;color:#e2e8f0">{items}</ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Job Pipeline Tracker</title>
  <style>
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
            background:#0f172a; color:#e2e8f0; padding:24px; }}
    h1   {{ font-size:22px; margin-bottom:4px; color:#f1f5f9; }}
    .sub {{ color:#64748b; font-size:13px; margin-bottom:24px; }}
    .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:24px; }}
    .card {{ background:#1e293b; border-radius:10px; padding:16px 20px; min-width:130px; }}
    .card .num {{ font-size:28px; font-weight:700; }}
    .card .lbl {{ font-size:12px; color:#94a3b8; margin-top:2px; }}
    table {{ width:100%; border-collapse:collapse; background:#1e293b;
             border-radius:10px; overflow:hidden; }}
    thead {{ background:#0f172a; }}
    th {{ padding:10px 12px; text-align:left; font-size:12px;
          color:#94a3b8; text-transform:uppercase; letter-spacing:0.05em; }}
    tr:hover td {{ background:#1d3048 !important; }}
    td {{ color:#cbd5e1; font-size:14px; vertical-align:middle; }}
  </style>
</head>
<body>
  <h1>🤖 Job Pipeline Tracker</h1>
  <p class="sub">Last updated: {now_str} &nbsp;|&nbsp; {total} total jobs tracked</p>

  <div class="cards">
    <div class="card">
      <div class="num" style="color:#22c55e">{applied}</div>
      <div class="lbl">Applied</div>
    </div>
    <div class="card">
      <div class="num" style="color:#3b82f6">{ready}</div>
      <div class="lbl">Ready to Apply</div>
    </div>
    <div class="card">
      <div class="num" style="color:#f97316">{manual}</div>
      <div class="lbl">Manual Queue</div>
    </div>
    <div class="card">
      <div class="num" style="color:#facc15">{queued}</div>
      <div class="lbl">Queued</div>
    </div>
    <div class="card">
      <div class="num" style="color:#f87171">{len(reminders)}</div>
      <div class="lbl">Follow-Ups Due</div>
    </div>
  </div>

  {reminder_html}

  <table>
    <thead>
      <tr>
        <th>Company</th>
        <th>Role</th>
        <th>Status</th>
        <th>Time</th>
        <th>Link</th>
      </tr>
    </thead>
    <tbody>{table_html}</tbody>
  </table>
</body>
</html>"""


def print_reminders(jobs):
    reminders = follow_up_reminders(jobs)
    if not reminders:
        print("No follow-ups due.")
        return
    print(f"\n⏰ Follow-Up Reminders ({len(reminders)} jobs applied {FOLLOWUP_DAYS}+ days ago):")
    for co, ti, u, days in reminders:
        print(f"  [{co}] {ti} — applied {days} days ago")
        print(f"  {u}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remind", action="store_true")
    args = parser.parse_args()

    jobs = load_jobs(DB_PATH)
    if not jobs:
        print("No jobs in database yet.")
        return

    if args.remind:
        print_reminders(jobs)
        return

    html = generate_html(jobs)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard saved: {os.path.abspath(HTML_OUT)}")
    print(f"Open: file:///{os.path.abspath(HTML_OUT).replace(os.sep, '/')}")
    print_reminders(jobs)


if __name__ == "__main__":
    main()