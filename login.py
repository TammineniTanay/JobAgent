from playwright.sync_api import sync_playwright

BROWSER_PROFILE = r"C:\Users\tanay\AppData\Local\Playwright\JobAgentProfile"

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(BROWSER_PROFILE, headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.linkedin.com")
    print("\n" + "="*50)
    print("  Log into LinkedIn in the browser window.")
    print("  Wait until you see your home feed.")
    print("="*50)
    input("\nPress Enter here ONLY after you are logged in > ")
    ctx.close()
    print("Done — profile saved.")