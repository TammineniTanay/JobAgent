"""
save_cookies.py
Run this ONCE to log into job sites and save your sessions permanently.
After running this, stage3_apply.py will never hit login walls again.
"""
from playwright.sync_api import sync_playwright

BROWSER_PROFILE = r"C:\Users\tanay\AppData\Local\Playwright\JobAgentProfile"

SITES = [
    ("LinkedIn",   "https://www.linkedin.com/login"),
    ("Greenhouse", "https://boards.greenhouse.io"),
    ("Lever",      "https://jobs.lever.co"),
    ("Workable",   "https://apply.workable.com"),
]

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(BROWSER_PROFILE, headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    print("\n" + "="*55)
    print("  SESSION SAVER")
    print("  Logs you into job sites and saves cookies forever.")
    print("="*55 + "\n")

    for name, url in SITES:
        print(f"Opening {name}...")
        page.goto(url)
        input(f"  Log into {name} normally, then press Enter > ")
        print(f"  ✓ {name} session saved\n")

    ctx.close()
    print("="*55)
    print("  All sessions saved to JobAgentProfile.")
    print("  stage3_apply.py will now skip all login walls.")
    print("="*55)
