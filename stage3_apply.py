"""
stage3_apply.py
Rebuilt with Playwright native fill() — far more reliable than JS injection.
Always grabs the latest active tab after user navigates manually.
"""

import sqlite3
import os
import re
import time
import random
import requests

OUTPUT_DIR = "output"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.1:8b"

# ─────────────────────────────────────────────────────────────────────────────
# YOUR INFO
# ─────────────────────────────────────────────────────────────────────────────

YOUR_INFO = {
    "first_name":    "Tanay",
    "last_name":     "Tammineni",
    "full_name":     "Tanay Tammineni",
    "email":         "tanaytammineni22@gmail.com",
    "phone_bare":    "8162779463",
    "phone_intl":    "+18162779463",
    "linkedin":      "https://www.linkedin.com/in/tanay-tammineni/",
    "github":        "https://github.com/TammineniTanay",
    "portfolio":     "https://tanaytammineni.vercel.app/",
    "location_full": "Irving, TX, United States",
    "city":          "Irving",
    "state_full":    "Texas",
    "state":         "TX",
    "zip":           "75062",
    "country":       "United States",
    "current_co":    "VoiceBotics AI",
    "current_title": "AI Systems Developer Intern",
    "university":    "Southeast Missouri State University",
    "degree":        "Master of Science in Computer Science",
    "grad_year":     "2025",
    "gpa":           "3.9",
    "years_exp":     "2",
    "salary":        "95000",
    "start_date":    "Immediately",
    "hear_about":    "Job Board",
}

CANDIDATE_CONTEXT = """
Tanay Tammineni — AI/ML Engineer
Current: AI Systems Developer Intern at VoiceBotics AI (Apr 2025-Present)
Previous: Software Engineer Intern at Globalshala (Jun 2022-Dec 2022)
Education: M.S. Computer Science, Southeast Missouri State University, GPA 3.9, Dec 2025
Location: Irving, TX. Skills: Python, PyTorch, LangChain, RAG, LLMs, FastAPI, AWS, Azure, Docker.
Work auth: Authorized in the US. No sponsorship needed.
"""

SKIP_LABELS = [
    "accommodat", "disability", "veteran", "race", "ethnicity",
    "gender", "pronoun", "demographic", "sexual", "military",
    "captcha", "csrf", "token", "referral code", "promo",
]

# ─────────────────────────────────────────────────────────────────────────────
# ATS DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

def detect_ats(url):
    u = url.lower()
    if "greenhouse.io" in u or "boards.greenhouse" in u or "gh_jid" in u:
        return "greenhouse"
    if "lever.co" in u or "jobs.lever" in u:    return "lever"
    if "workday" in u or "myworkdayjobs" in u:  return "workday"
    if "oraclecloud" in u or "fa.em" in u:      return "oracle"
    if "taleo" in u:                            return "taleo"
    if "smartrecruiters" in u:                  return "smartrecruiters"
    if "paylocity" in u:                        return "paylocity"
    if "workable" in u:                         return "workable"
    if "rippling" in u:                         return "rippling"
    if "ultipro" in u:                          return "ultipro"
    if "adp" in u:                              return "adp"
    if "ashbyhq" in u or "ashby" in u:          return "ashby"
    if "bamboohr" in u:                         return "bamboohr"
    if "jobvite" in u:                          return "jobvite"
    if "personio" in u:                         return "personio"
    if "paycor" in u:                           return "paycor"
    if "icims" in u:                            return "icims"
    if "dayforcehcm" in u:                      return "dayforce"
    if "google.com/about/careers" in u:         return "google"
    if "apple.com" in u:                        return "apple"
    if "amazon.jobs" in u:                      return "amazon"
    return "unknown"

MANUAL_ONLY = {"google", "apple", "amazon", "oracle", "taleo"}

# ─────────────────────────────────────────────────────────────────────────────
# GET ACTIVE PAGE — always returns the most recently used tab
# ─────────────────────────────────────────────────────────────────────────────

def get_active_page(ctx):
    """
    Returns the page the user is currently looking at.
    Gets the last tab in context — the one most recently opened/focused.
    """
    pages = ctx.pages
    if not pages:
        return ctx.new_page()
    # return the last page (most recently opened)
    return pages[-1]


def get_live_page(ctx, page):
    try:
        page.title()
        return page
    except Exception:
        return ctx.new_page()

# ─────────────────────────────────────────────────────────────────────────────
# FILE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_output_dir(company, title):
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", f"{company}_{title}")[:55]
    if os.path.isdir(OUTPUT_DIR):
        date_dirs = sorted(
            [d for d in os.listdir(OUTPUT_DIR)
             if re.match(r"\d{4}-\d{2}-\d{2}", d)
             and os.path.isdir(os.path.join(OUTPUT_DIR, d))],
            reverse=True
        )
        for dd in date_dirs:
            cand = os.path.join(OUTPUT_DIR, dd, safe)
            if os.path.isdir(cand):
                return cand
    return os.path.join(OUTPUT_DIR, safe)


def find_file(job_dir, doc_type="resume", ext="pdf"):
    direct = os.path.join(job_dir, f"{doc_type}.{ext}")
    if os.path.exists(direct):
        return direct
    if os.path.isdir(job_dir):
        for f in os.listdir(job_dir):
            name = f.lower().replace("_", "").replace("-", "")
            key  = doc_type.lower().replace("_", "")
            if f.endswith(f".{ext}") and key in name:
                return os.path.join(job_dir, f)
    return None


def load_cover_letter_text(job_dir):
    tex = os.path.join(job_dir, "cover_letter.tex")
    if not os.path.exists(tex):
        return ""
    try:
        content = open(tex, encoding="utf-8").read()
        m = re.search(r"\\normalsize\s*\n+(.*?)\\vspace\{8pt\}", content, re.DOTALL)
        if not m:
            return ""
        text = m.group(1)
        text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\[a-zA-Z]+", "", text)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return ""

# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA
# ─────────────────────────────────────────────────────────────────────────────

def ask_ollama(question, job_title, company, jd_snippet, cl_text):
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL_NAME,
            "prompt": (
                f"Fill this job application field for Tanay Tammineni.\n"
                f"Candidate: {CANDIDATE_CONTEXT}\n"
                f"Job: {job_title} at {company}\n"
                f"JD: {jd_snippet[:300]}\n"
                f'Field: "{question}"\n'
                f"Write 1-3 sentences max 60 words. No visa mentions. Answer only."
            ),
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 1200},
        }, timeout=45)
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception:
        pass
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# DELAYS
# ─────────────────────────────────────────────────────────────────────────────

def pause(lo=0.5, hi=1.5):
    time.sleep(random.uniform(lo, hi))

# ─────────────────────────────────────────────────────────────────────────────
# CORE FILL FUNCTION — uses Playwright native fill(), not JS
# ─────────────────────────────────────────────────────────────────────────────

def smart_fill(page, value):
    """
    Fill a Playwright locator with a value.
    Uses native fill() which properly triggers React/Vue state.
    Falls back to JS nativeInputValueSetter if fill() doesn't work.
    """
    if not value:
        return False
    try:
        # Playwright native fill — triggers all React events automatically
        page.fill("", str(value))
        return True
    except Exception:
        pass
    return False


def fill_input(locator, value):
    """Fill a single input field with proper event triggering."""
    if not value:
        return False
    try:
        if locator.count() == 0:
            return False
        el = locator.first
        if not el.is_visible(timeout=1000):
            return False
        # clear first, then fill
        el.click()
        pause(0.1, 0.2)
        el.fill("")
        el.fill(str(value))
        pause(0.1, 0.2)
        return True
    except Exception:
        pass
    # JS fallback
    try:
        el = locator.first
        safe_val = str(value).replace("'", "\\'").replace("\n", " ")
        el.evaluate(f"""inp => {{
            var s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            s.call(inp, '{safe_val}');
            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
            inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
        }}""")
        return True
    except Exception:
        pass
    return False


def fill_by_label(page, label_text, value):
    """Fill input associated with a label. Most reliable method."""
    if not value:
        return False
    # try Playwright's get_by_label — handles aria-label, for=, nested
    for exact in [True, False]:
        try:
            loc = page.get_by_label(label_text, exact=exact)
            if loc.count() > 0 and loc.first.is_visible(timeout=800):
                loc.first.click()
                pause(0.1, 0.2)
                loc.first.fill(str(value))
                pause(0.1, 0.2)
                return True
        except Exception:
            pass
    return False


def fill_by_placeholder(page, placeholder_text, value):
    """Fill input by placeholder text."""
    if not value:
        return False
    try:
        loc = page.get_by_placeholder(placeholder_text, exact=False)
        if loc.count() > 0 and loc.first.is_visible(timeout=800):
            loc.first.click()
            pause(0.1, 0.2)
            loc.first.fill(str(value))
            return True
    except Exception:
        pass
    return False


def select_dropdown_option(page, label_text, options):
    """Select from a <select> dropdown by label."""
    try:
        loc = page.get_by_label(label_text, exact=False)
        if loc.count() > 0:
            el = loc.first
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            if tag == "select":
                for opt in options:
                    try:
                        el.select_option(label=opt)
                        pause(0.2, 0.4)
                        return True
                    except Exception:
                        try:
                            el.select_option(value=opt)
                            pause(0.2, 0.4)
                            return True
                        except Exception:
                            continue
    except Exception:
        pass

    # scan all selects on page
    try:
        selects = page.locator("select").all()
        for sel in selects:
            try:
                # get label for this select
                nearby = sel.evaluate("""el => {
                    if (el.id) {
                        let l = document.querySelector('label[for="' + el.id + '"]');
                        if (l) return l.innerText.toLowerCase();
                    }
                    let p = el.parentElement;
                    for (let i = 0; i < 5; i++) {
                        if (!p) break;
                        let l = p.querySelector('label');
                        if (l) return l.innerText.toLowerCase();
                        p = p.parentElement;
                    }
                    return (el.getAttribute('aria-label') || el.name || '').toLowerCase();
                }""")
                if label_text.lower() not in (nearby or ""):
                    continue
                for opt in options:
                    try:
                        sel.select_option(label=opt)
                        pause(0.2, 0.4)
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass
    return False


def click_react_dropdown(page, label_text, options):
    """Handle custom React/Vue dropdowns (not native select)."""
    try:
        labels = page.locator("label").all()
        for lbl in labels:
            try:
                lt = lbl.inner_text().strip().lower()
                if label_text.lower() not in lt:
                    continue
                for_id = lbl.get_attribute("for") or ""

                # find the dropdown trigger
                trigger = None
                if for_id:
                    el = page.locator(f"#{for_id}").first
                    if el.count() > 0:
                        tag = el.evaluate("e => e.tagName.toLowerCase()")
                        if tag != "select":
                            trigger = el

                if not trigger:
                    for sel in ['[role="combobox"]', '[class*="dropdown__control"]',
                                '[class*="Select__control"]', '[class*="select__control"]']:
                        t = page.locator(sel).first
                        if t.count() > 0 and t.is_visible(timeout=500):
                            trigger = t
                            break

                if not trigger:
                    continue

                # check if already has value
                try:
                    cur = trigger.inner_text().strip().lower()
                    if cur and cur not in ("select...", "select", "-- select --", ""):
                        return True  # already filled
                except Exception:
                    pass

                trigger.click()
                pause(0.5, 1.0)

                for opt in options:
                    for os_ in [
                        f'[role="option"]:has-text("{opt}")',
                        f'li:has-text("{opt}")',
                        f'div[class*="option"]:has-text("{opt}")',
                        f'span:has-text("{opt}")',
                    ]:
                        try:
                            oe = page.locator(os_).first
                            if oe.count() > 0 and oe.is_visible(timeout=1000):
                                oe.click()
                                pause(0.3, 0.5)
                                return True
                        except Exception:
                            continue

                page.keyboard.press("Escape")
                pause(0.2, 0.3)
            except Exception:
                continue
    except Exception:
        pass
    return False

# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD FILES
# ─────────────────────────────────────────────────────────────────────────────

def upload_files(page, resume_pdf, cl_pdf):
    inputs = page.locator('input[type="file"]').all()
    resume_done = False
    cl_done     = False
    for fi in inputs:
        try:
            nearby = fi.evaluate("""el => {
                let p = el.closest('[class*="field"],[class*="upload"],div,section');
                return p ? p.innerText.toLowerCase() : '';
            }""")
            is_cover = "cover" in nearby
            if is_cover and cl_pdf and not cl_done:
                fi.set_input_files(cl_pdf); pause(1.5, 2.5); cl_done = True
            elif not is_cover and resume_pdf and not resume_done:
                fi.set_input_files(resume_pdf); pause(1.5, 2.5); resume_done = True
        except Exception:
            continue
    if not resume_done and resume_pdf:
        for fi in page.locator('input[type="file"]').all():
            try:
                fi.set_input_files(resume_pdf); pause(1.5, 2.5)
                resume_done = True; break
            except Exception:
                continue
    return resume_done

# ─────────────────────────────────────────────────────────────────────────────
# MAIN FILL — uses Playwright native methods
# ─────────────────────────────────────────────────────────────────────────────

def fill_all_fields(page, resume_pdf, cl_pdf, job_dir, company, title, jd_text):
    """
    Fill every field using Playwright native fill() + get_by_label().
    Much more reliable than JS injection.
    """
    cl_text    = load_cover_letter_text(job_dir)
    jd_snippet = (jd_text or "")[:500]

    # build why-us answer
    why_us = ""
    if cl_text:
        paras = [p.strip() for p in re.split(r"\s{3,}", cl_text) if len(p.strip()) > 20]
        why_us = paras[1] if len(paras) > 1 else (paras[0] if paras else "")
    if not why_us:
        why_us = (f"I am drawn to {company} because its work aligns with my "
                  f"experience building production LLM pipelines and RAG systems.")

    # scroll to load all content
    try:
        page.evaluate("window.scrollTo(0, 0)")
        pause(0.5, 0.8)
    except Exception:
        pass

    # ── 1. File uploads ──────────────────────────────────────────────────────
    upload_files(page, resume_pdf, cl_pdf)
    pause(0.5, 1.0)

    # ── 2. Detect phone format ───────────────────────────────────────────────
    has_cc = False
    try:
        has_cc = page.evaluate("""() => {
            let els = document.querySelectorAll('input, select');
            for (let e of els) {
                let c = (e.placeholder || '').toLowerCase() + (e.name || '').toLowerCase();
                if (c.includes('country code') || c.includes('country_code')) return true;
            }
            return document.querySelectorAll('[class*="flag"],[class*="country-code"],[class*="dial-code"]').length > 0;
        }""")
    except Exception:
        pass
    phone_val = YOUR_INFO["phone_bare"] if has_cc else YOUR_INFO["phone_intl"]

    # ── 3. Fill text fields using get_by_label ───────────────────────────────
    # Each entry: (label patterns to try, value)
    text_fields = [
        (["First Name", "Legal First Name", "Given Name", "Preferred First Name"], YOUR_INFO["first_name"]),
        (["Last Name", "Legal Last Name", "Family Name", "Surname"],               YOUR_INFO["last_name"]),
        (["Full Name", "Legal Name", "Name"],                                      YOUR_INFO["full_name"]),
        (["Email", "Email Address", "Email address"],                              YOUR_INFO["email"]),
        (["Phone", "Phone Number", "Mobile", "Mobile Number", "Cell"],             phone_val),
        (["LinkedIn", "LinkedIn Profile", "LinkedIn URL"],                         YOUR_INFO["linkedin"]),
        (["Website", "Portfolio", "Personal Website", "Personal URL",
          "Personal Site"],                                                         YOUR_INFO["portfolio"]),
        (["GitHub", "Github"],                                                     YOUR_INFO["github"]),
        # Location — try full first to avoid city overwriting it
        (["Location: City, Region, Country", "Location: City, State, Country",
          "City, Region, Country", "City, State, Country"],                        YOUR_INFO["location_full"]),
        (["City"],                                                                 YOUR_INFO["city"]),
        (["State", "State / Province", "Province"],                               YOUR_INFO["state_full"]),
        (["Zip", "Zip Code", "Postal Code"],                                      YOUR_INFO["zip"]),
        (["Country"],                                                              YOUR_INFO["country"]),
        (["Current Company", "Current Employer", "Company", "Employer",
          "Organization"],                                                          YOUR_INFO["current_co"]),
        (["Current Title", "Current Position", "Job Title", "Position"],          YOUR_INFO["current_title"]),
        (["University", "College", "School", "Institution"],                      YOUR_INFO["university"]),
        (["Degree", "Field of Study", "Major"],                                   YOUR_INFO["degree"]),
        (["Graduation Year", "Grad Year", "Expected Graduation"],                 YOUR_INFO["grad_year"]),
        (["GPA"],                                                                  YOUR_INFO["gpa"]),
        (["Years of Experience", "How many years"],                               YOUR_INFO["years_exp"]),
        (["Salary", "Expected Salary", "Desired Salary", "Compensation",
          "Expected Pay"],                                                          YOUR_INFO["salary"]),
        (["Start Date", "When can you start", "Available to start"],              YOUR_INFO["start_date"]),
        (["How did you hear", "Referral Source", "Where did you find"],           YOUR_INFO["hear_about"]),
    ]

    for label_variants, value in text_fields:
        for label in label_variants:
            if fill_by_label(page, label, value):
                break
            if fill_by_placeholder(page, label, value):
                break

    pause(0.5, 0.8)

    # ── 4. Dropdowns ─────────────────────────────────────────────────────────
    dropdown_fields = [
        ("authorized",    ["authorized to work", "legally authorized", "work auth", "eligible to work"],
         ["Yes", "Yes, I am authorized", "Authorized"]),
        ("sponsor",       ["sponsorship", "require sponsor", "visa sponsor", "H-1B", "immigration"],
         ["No", "No, I do not", "Not required"]),
        ("country",       ["country", "country of residence"],
         ["United States", "United States of America", "USA"]),
        ("state",         ["state", "state / province", "province"],
         ["Texas", "TX"]),
        ("education",     ["education level", "highest education", "degree level"],
         ["Master", "Master's", "Master's Degree", "Graduate"]),
        ("emp_type",      ["employment type", "job type", "position type"],
         ["Full-time", "Full Time", "Permanent"]),
        ("exp_years",     ["years of experience"],
         ["0-2", "1-3", "2", "Entry Level"]),
    ]

    for key, label_variants, options in dropdown_fields:
        for label in label_variants:
            if select_dropdown_option(page, label, options):
                break
            if click_react_dropdown(page, label, options):
                break

    pause(0.3, 0.5)

    # ── 5. Radio buttons ─────────────────────────────────────────────────────
    try:
        for radio in page.locator('input[type="radio"]').all():
            try:
                if not radio.is_visible(timeout=300):
                    continue
                nearby = radio.evaluate("""el => {
                    let lbl = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
                    if (lbl) return lbl.innerText.toLowerCase();
                    let p = el.parentElement;
                    for (let i = 0; i < 4; i++) {
                        if (!p) break;
                        let t = p.innerText || '';
                        if (t.trim().length > 2) return t.toLowerCase();
                        p = p.parentElement;
                    }
                    return (el.value || '').toLowerCase();
                }""")
                val  = (radio.get_attribute("value") or "").lower()
                comb = nearby + " " + val
                if (re.search(r"authorized|legally.*work|eligible", nearby, re.IGNORECASE) and
                        re.search(r"\byes\b|authorized|eligible", comb, re.IGNORECASE)):
                    radio.click(); pause(0.2, 0.3)
                elif (re.search(r"sponsor|visa|h.?1.?b", nearby, re.IGNORECASE) and
                        re.search(r"\bno\b|not require", comb, re.IGNORECASE)):
                    radio.click(); pause(0.2, 0.3)
            except Exception:
                continue
    except Exception:
        pass

    # ── 6. Agreement checkboxes ───────────────────────────────────────────────
    try:
        for cb in page.locator('input[type="checkbox"]').all():
            try:
                if not cb.is_visible(timeout=300):
                    continue
                nearby = cb.evaluate("""el => {
                    let lbl = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
                    if (lbl) return lbl.innerText.toLowerCase();
                    return (el.parentElement || {innerText: ''}).innerText.toLowerCase();
                }""")
                if re.search(r"agree|certif|confirm|terms|accept|acknowledge", nearby, re.IGNORECASE):
                    if not cb.is_checked():
                        cb.click(); pause(0.2, 0.3)
            except Exception:
                continue
    except Exception:
        pass

    # ── 7. Open-ended textareas ───────────────────────────────────────────────
    open_map = [
        (r"cover\s*letter",                                             cl_text[:1200] if cl_text else why_us),
        (r"why.{0,50}(company|role|position|join|interest|us\b|here)", why_us[:600]),
        (r"tell.{0,20}(about yourself|yourself|background)|introduce", cl_text[:600] if cl_text else why_us),
        (r"what.{0,30}(excite|interest|draw|attract|motivat)",          why_us[:500]),
        (r"additional.{0,30}(info|comment|detail)|anything\s*else",     why_us[:400]),
        (r"how.{0,30}(contribute|add\s*value|help)",                    why_us[:500]),
    ]

    try:
        for ta in page.locator("textarea").all():
            try:
                if not ta.is_visible(timeout=300):
                    continue
                cur = ta.input_value()
                if cur and len(cur.strip()) > 15:
                    continue
                # get label
                label_text = ""
                ta_id = ta.get_attribute("id") or ""
                if ta_id:
                    lbl = page.locator(f'label[for="{ta_id}"]').first
                    if lbl.count() > 0:
                        label_text = lbl.inner_text().strip()
                if not label_text:
                    label_text = (ta.get_attribute("placeholder") or
                                  ta.get_attribute("name") or
                                  ta.get_attribute("aria-label") or "")
                ll = label_text.lower()

                # skip sensitive
                if any(s in ll for s in SKIP_LABELS):
                    continue

                filled = False
                for pat, ans in open_map:
                    if re.search(pat, ll, re.IGNORECASE):
                        ta.click(); pause(0.3, 0.5)
                        ta.fill(ans); pause(0.2, 0.3)
                        filled = True
                        break

                if not filled and len(label_text) > 5:
                    print(f"    Unknown question: '{label_text[:55]}' — asking Ollama...")
                    ans = ask_ollama(label_text, title, company, jd_snippet, cl_text)
                    if ans and len(ans) > 5:
                        ta.click(); pause(0.3, 0.5)
                        ta.fill(ans[:600]); pause(0.2, 0.3)
            except Exception:
                continue
    except Exception:
        pass

    # ── 8. Scroll down and fill again (catches late-loading fields) ───────────
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
        pause(1.0, 1.5)
    except Exception:
        pass

    # second pass for links + dropdowns after scroll
    for label_variants, value in text_fields[:8]:  # top 8 = most important fields
        for label in label_variants:
            if fill_by_label(page, label, value):
                break

    for key, label_variants, options in dropdown_fields:
        for label in label_variants:
            if select_dropdown_option(page, label, options):
                break
            if click_react_dropdown(page, label, options):
                break

# ─────────────────────────────────────────────────────────────────────────────
# NAVIGATE TO FORM
# ─────────────────────────────────────────────────────────────────────────────

def navigate_to_form(page, ctx, url, ats):
    """Try to get to the actual form. Returns (page, success)."""
    tabs_before = len(ctx.pages)

    # SmartRecruiters — append /apply
    if ats == "smartrecruiters":
        apply_url = url.split("?")[0].rstrip("/") + "/apply"
        try:
            page.goto(apply_url, timeout=30000, wait_until="domcontentloaded")
            pause(3, 5)
            n = page.locator('input:not([type="hidden"])').count()
            print(f"  SmartRecruiters /apply → {n} inputs")
            if n > 2:
                return page, True
        except Exception as e:
            print(f"  /apply failed: {e}")

    # Ashby — append /apply
    if ats == "ashby":
        apply_url = url.split("?")[0].rstrip("/") + "/apply"
        try:
            page.goto(apply_url, timeout=30000, wait_until="domcontentloaded")
            pause(3, 5)
            n = page.locator('input:not([type="hidden"])').count()
            if n > 2:
                return page, True
        except Exception:
            pass

    # generic Apply button
    for sel in [
        'button:has-text("Apply for this job")',
        'button:has-text("Apply Now")',
        'button:has-text("Apply now")',
        'button:has-text("Apply")',
        'a:has-text("Apply for this job")',
        'a:has-text("Apply Now")',
        'a:has-text("Apply")',
        '[data-ui="apply-button"]',
        '[data-qa="btn-apply"]',
        '[class*="apply-button"]',
        '[class*="applyButton"]',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible(timeout=1500):
                btn.click()
                pause(3, 5)
                all_pages = ctx.pages
                if len(all_pages) > tabs_before:
                    new_page = all_pages[-1]
                    new_page.bring_to_front()
                    pause(2, 3)
                    n = new_page.locator('input:not([type="hidden"])').count()
                    print(f"  New tab → {n} inputs")
                    if n > 0:
                        return new_page, True
                n = page.locator('input:not([type="hidden"])').count()
                if n > 2:
                    print(f"  Apply clicked → {n} inputs")
                    return page, True
        except Exception:
            continue

    # check if form already on page
    n = page.locator('input:not([type="hidden"])').count()
    if n > 3:
        print(f"  Form already on page → {n} inputs")
        return page, True

    return page, False


def check_confirmation(page):
    try:
        txt = page.locator("body").inner_text().lower()
        return any(x in txt for x in [
            "application submitted", "application received",
            "thank you for applying", "thanks for applying",
            "successfully submitted", "successfully applied",
            "we've received your application", "application complete",
            "you have applied", "we will be in touch",
        ])
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main(db_path="job_agent.db"):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pip install playwright && playwright install chromium")
        return {}

    conn = sqlite3.connect(db_path)
    c    = conn.cursor()
    c.execute("""
        SELECT jobpostingid, company, title, url, status, jd_text
        FROM seen_jobs
        WHERE status IN ('GENERATED_YES','GENERATED_MAYBE')
        ORDER BY CASE status WHEN 'GENERATED_YES' THEN 0 ELSE 1 END, date_found DESC
    """)
    jobs  = c.fetchall()
    total = len(jobs)

    if not jobs:
        print("No jobs to apply. Run stage2 first or reset manual jobs.")
        conn.close()
        return {}

    print(f"\n=== Stage 3: {total} job(s) ===")
    print(f"  LinkedIn:  {YOUR_INFO['linkedin']}")
    print(f"  Portfolio: {YOUR_INFO['portfolio']}")
    print(f"  GitHub:    {YOUR_INFO['github']}")
    print(f"\n  HOW IT WORKS:")
    print(f"  - Bot opens job, tries to find the form automatically")
    print(f"  - If not found → YOU click Apply in the browser")
    print(f"    Press Enter once you see the APPLICATION FORM")
    print(f"    Bot then fills all fields using native Playwright methods")
    print(f"  - Review, fix anything, click SUBMIT")
    print(f"  - Enter = submitted,  s = skip\n")

    results = {"applied": 0, "skipped": 0, "no_pdf": 0}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        ctx  = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        for idx, (job_id, company, title, url, job_status, jd_text) in enumerate(jobs, 1):
            ats     = detect_ats(url)
            job_dir = get_output_dir(company, title)
            res_pdf = find_file(job_dir, "resume", "pdf")
            cl_pdf  = find_file(job_dir, "cover_letter", "pdf")

            print(f"\n{'─'*55}")
            print(f"[{idx}/{total}] [{job_status.replace('GENERATED_','')}] [{company}]")
            print(f"Role:   {title}")
            print(f"ATS:    {ats.upper()}")
            print(f"Resume: {res_pdf or 'NOT FOUND'}")

            if not res_pdf:
                tex = find_file(job_dir, "resume", "tex")
                print(f"  -> {'Compile resume.tex at overleaf.com' if tex else 'Run stage2 first'}")
                c.execute("UPDATE seen_jobs SET status='MANUAL_NO_PDF' WHERE jobpostingid=?", (job_id,))
                conn.commit()
                results["no_pdf"] += 1
                continue

            # ensure tab is alive
            page = get_live_page(ctx, page)

            # manual-only portals
            if ats in MANUAL_ONLY:
                print(f"  {ats.upper()} — opening for manual apply")
                print(f"  Resume: {res_pdf}")
                try:
                    page = get_live_page(ctx, page)
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    pause(2, 3)
                except Exception:
                    pass
                choice = input("  [Enter = applied,  s = skip] > ").strip().lower()
                if choice == "s":
                    c.execute("UPDATE seen_jobs SET status='MANUAL_APPLY' WHERE jobpostingid=?", (job_id,))
                    results["skipped"] += 1
                else:
                    c.execute("UPDATE seen_jobs SET status='APPLIED' WHERE jobpostingid=?", (job_id,))
                    results["applied"] += 1
                conn.commit()
                continue

            # navigate
            print(f"  Navigating...")
            nav_ok = False
            for attempt in range(2):
                try:
                    page = get_live_page(ctx, page)
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    pause(3, 5)
                    nav_ok = True
                    break
                except Exception as e:
                    if attempt == 0:
                        page = ctx.new_page()
                    else:
                        print(f"  Nav failed: {e}")

            if not nav_ok:
                choice = input("  [Enter = skip,  s = skip] > ").strip().lower()
                c.execute("UPDATE seen_jobs SET status='MANUAL_APPLY' WHERE jobpostingid=?", (job_id,))
                conn.commit()
                results["skipped"] += 1
                continue

            # try to get to form
            print(f"  Looking for application form...")
            page, form_found = navigate_to_form(page, ctx, url, ats)

            if not form_found:
                print(f"\n  ┌────────────────────────────────────────────────────┐")
                print(f"  │  Form not found automatically.                      │")
                print(f"  │  In the browser: click Apply / find the form.       │")
                print(f"  │  Once you see INPUT FIELDS on screen → press Enter  │")
                print(f"  └────────────────────────────────────────────────────┘")
                input("  [Press Enter when you are ON the application form] > ")
                pause(1, 2)

            # !! CRITICAL: always get the LATEST active page !!
            # if user opened a new tab, we must use that tab, not the old one
            page = get_active_page(ctx)
            n = page.locator('input:not([type="hidden"])').count()
            print(f"  Active tab: {page.url[:70]}")
            print(f"  Input fields visible: {n}")

            if n == 0:
                print(f"  No fields found on active tab.")
                print(f"  Make sure the APPLICATION FORM is visible, then press Enter.")
                input("  > ")
                page = get_active_page(ctx)
                n = page.locator('input:not([type="hidden"])').count()
                print(f"  Input fields now: {n}")

            # fill
            print(f"  Filling form...")
            try:
                fill_all_fields(page, res_pdf, cl_pdf, job_dir, company, title, jd_text or "")
            except Exception as e:
                print(f"  Fill error: {e}")

            print(f"\n  ✅ Fill complete — review in browser:")
            print(f"  🔍 Check: name, email, phone, LinkedIn, portfolio, dropdowns")
            print(f"  ✏️  Fix anything → click SUBMIT")
            print()
            choice = input("  [Enter = I submitted,  s = skip] > ").strip().lower()

            if choice == "s":
                print(f"  -> Skipped")
                c.execute("UPDATE seen_jobs SET status='MANUAL_APPLY' WHERE jobpostingid=?", (job_id,))
                conn.commit()
                results["skipped"] += 1
                continue

            time.sleep(2)
            # get active page again in case user navigated
            page = get_active_page(ctx)
            if check_confirmation(page):
                print(f"  -> ✅ Confirmation detected!")
            else:
                print(f"  -> Marked APPLIED (check {YOUR_INFO['email']})")

            c.execute("UPDATE seen_jobs SET status='APPLIED' WHERE jobpostingid=?", (job_id,))
            conn.commit()
            results["applied"] += 1
            pause(2, 3)

        print(f"\n{'='*55}")
        print(f"All {total} jobs done.")
        input("Press Enter to close browser > ")
        browser.close()

    print(f"\n=== Results ===")
    print(f"  Applied:  {results['applied']}")
    print(f"  Skipped:  {results['skipped']}")
    print(f"  No PDF:   {results['no_pdf']}")
    conn.close()
    return results


if __name__ == "__main__":
    main()