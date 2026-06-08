"""
stage3_apply.py  —  Modular ATS Handler Architecture

Architecture:
- ATSHandler base class: Strategy Pattern, one handler per ATS platform
- Dedicated handlers: Greenhouse, Lever, Workable, SmartRecruiters, Ashby, Generic
- Native Playwright fill() with force=True — bypasses sticky headers
- 4-strategy dropdown: native select → Select2 → React-Select → keyboard nav
- Accessibility Tree fallback — works on ANY website regardless of CSS framework
- Greenhouse API interception — bypass UI entirely, POST directly to backend
- iFrame traversal — finds forms inside embedded iframes
- Stealth mode — randomized viewport, humanized typing delays
- SQLite WAL mode + with conn: context managers — no corruption on crash
- Ollama cached per job for open questions

Add new ATS: subclass ATSHandler, override apply(), register in HANDLERS dict.
"""

import sqlite3
import os
import re
import time
import random
import subprocess
import requests
import json as _json
from abc import ABC, abstractmethod

OUTPUT_DIR      = "output"
OLLAMA_URL      = "http://localhost:11434/api/generate"
MODEL_NAME      = "llama3.1:8b"
BROWSER_PROFILE = r"C:\Users\tanay\AppData\Local\Playwright\JobAgentProfile"

# ── Humanized typing: random delay per keystroke (10–45ms) mimics human ──────
def _human_delay():
    return random.randint(10, 45)

# ─────────────────────────────────────────────────────────────────────────────
# CANDIDATE INFO
# ─────────────────────────────────────────────────────────────────────────────

INFO = {
    "first":     "Tanay",
    "last":      "Tammineni",
    "full":      "Tanay Tammineni",
    "email":     "tanaytammineni22@gmail.com",
    "phone":     "8162779463",
    "phone_i":   "+18162779463",
    "linkedin":  "https://www.linkedin.com/in/tanay-tammineni/",
    "github":    "https://github.com/TammineniTanay",
    "portfolio": "https://tanaytammineni.vercel.app/",
    "street":    "871 Lake Carolyn Pkwy, Apt 374",
    "city":      "Irving",
    "state":     "Texas",
    "state_s":   "TX",
    "zip":       "75039",
    "country":   "United States",
    "location":  "Irving, TX, United States",
    "company":   "VoiceBotics AI",
    "title":     "AI Systems Developer Intern",
    "university":"Southeast Missouri State University",
    "degree_s":  "Master's",
    "grad_year": "2025",
    "gpa":       "3.9",
    "years_exp": "2",
    "salary":    "95000",
    "start":     "Immediately",
    "hear":      "Job Board",
}

CANDIDATE_BIO = (
    "Tanay Tammineni, AI/ML Engineer, Irving TX. "
    "Current: AI Systems Developer Intern at VoiceBotics AI (Apr 2025). "
    "Education: M.S. CS, Southeast Missouri State University, GPA 3.9, Dec 2025. "
    "Skills: Python, PyTorch, LangChain, RAG, LLMs, FastAPI, AWS, Docker. "
    "Work auth: Authorized in the US. No sponsorship needed. Willing to relocate anywhere."
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def detect_ats(url):
    u = url.lower()
    if "linkedin.com" in u:                         return "linkedin"
    if "greenhouse.io" in u or "gh_jid" in u:       return "greenhouse"
    if "lever.co" in u or "jobs.lever" in u:        return "lever"
    if "workday" in u or "myworkdayjobs" in u:      return "workday"
    if "oraclecloud" in u or "fa.em" in u:          return "oracle"
    if "taleo" in u:                                return "taleo"
    if "smartrecruiters" in u:                      return "smartrecruiters"
    if "paylocity" in u:                            return "paylocity"
    if "workable" in u:                             return "workable"
    if "rippling" in u:                             return "rippling"
    if "ultipro" in u:                              return "ultipro"
    if "ashbyhq" in u or "ashby" in u:              return "ashby"
    if "bamboohr" in u:                             return "bamboohr"
    if "personio" in u:                             return "personio"
    if "paycor" in u:                               return "paycor"
    if "icims" in u:                                return "icims"
    if "google.com/about/careers" in u:             return "google"
    if "apple.com" in u:                            return "apple"
    if "amazon.jobs" in u:                          return "amazon"
    return "unknown"


def get_output_dir(company, title):
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", f"{company}_{title}")[:55]
    if os.path.isdir(OUTPUT_DIR):
        for dd in sorted(
            [d for d in os.listdir(OUTPUT_DIR)
             if re.match(r"\d{4}-\d{2}-\d{2}", d)
             and os.path.isdir(os.path.join(OUTPUT_DIR, d))],
            reverse=True
        ):
            p = os.path.join(OUTPUT_DIR, dd, safe)
            if os.path.isdir(p):
                return p
    return os.path.join(OUTPUT_DIR, safe)


def find_file(job_dir, doc_type="resume", ext="pdf"):
    direct = os.path.join(job_dir, f"{doc_type}.{ext}")
    if os.path.exists(direct):
        return direct
    if os.path.isdir(job_dir):
        for f in os.listdir(job_dir):
            n = f.lower().replace("_", "").replace("-", "")
            k = doc_type.lower().replace("_", "")
            if f.endswith(f".{ext}") and k in n:
                return os.path.join(job_dir, f)
    return None


def load_cl_text(job_dir):
    tex = os.path.join(job_dir, "cover_letter.tex")
    if not os.path.exists(tex):
        return ""
    try:
        c = open(tex, encoding="utf-8").read()
        m = re.search(r"\\normalsize\s*\n+(.*?)\\vspace", c, re.DOTALL)
        if not m:
            return ""
        t = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", m.group(1))
        t = re.sub(r"\\[a-zA-Z]+", "", t)
        return re.sub(r"\s+", " ", t).strip()
    except Exception:
        return ""


def open_folder(path):
    try:
        if path and os.path.isdir(path):
            subprocess.Popen(["explorer", os.path.abspath(path)])
    except Exception:
        pass


def get_active_page(ctx):
    return ctx.pages[-1] if ctx.pages else ctx.new_page()

# ─────────────────────────────────────────────────────────────────────────────
# iFrame TRAVERSAL — finds elements across all frames
# ─────────────────────────────────────────────────────────────────────────────

def find_frame_with_form(page):
    """
    Returns the frame that contains the application form.
    Checks main page first, then all nested frames.
    Looks for frame with the most non-hidden inputs.
    """
    best_frame = page
    best_count = 0

    # count inputs in main frame
    try:
        n = page.locator('input:not([type="hidden"])').count()
        if n > best_count:
            best_count = n
            best_frame = page
    except Exception:
        pass

    # check all nested frames
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            n = frame.locator('input:not([type="hidden"])').count()
            if n > best_count:
                best_count = n
                best_frame = frame
        except Exception:
            continue

    return best_frame, best_count


def find_element_across_frames(page, selector):
    """
    Finds a locator across the main page and all iframes.
    Returns (frame, locator) for the first match found.
    """
    # try main page first
    try:
        loc = page.locator(selector)
        if loc.count() > 0 and loc.first.is_visible(timeout=500):
            return page, loc
    except Exception:
        pass
    # try all frames
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            loc = frame.locator(selector)
            if loc.count() > 0 and loc.first.is_visible(timeout=500):
                return frame, loc
        except Exception:
            continue
    return page, page.locator(selector)

# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA — with per-job cache
# ─────────────────────────────────────────────────────────────────────────────

_CACHE: dict = {}

def ask_ollama(question, company, job_title, jd_snip, cl_text):
    key = re.sub(r"\s+", " ", question.lower().strip())[:80]
    if key in _CACHE:
        return _CACHE[key]

    def c(v):
        _CACHE[key] = v
        return v

    q = question.lower()
    if re.search(r"authorized|legally.*work|eligible.*work|without.*sponsor", q):
        return c("Yes")
    if re.search(r"require.*sponsor|need.*sponsor|visa|h.?1.?b|\bopt\b|sponsorship", q):
        return c("No")
    if re.search(r"reloca|willing to move", q):
        return c("Yes, I am open to relocating anywhere in the United States.")
    if re.search(r"salary|compensation|expected.*pay", q):
        return c("95000")
    if re.search(r"start.*date|when.*start|available.*start", q):
        return c("Immediately")
    if re.search(r"years.*experience|how many years", q):
        return c("2")
    if re.search(r"hear about|referral|where did you", q):
        return c("Job Board")
    cities = ["san diego","boston","new york","chicago","seattle","austin","dallas","san francisco"]
    for city in cities:
        if city in q and re.search(r"based in|located in|live in|reside in", q):
            return c("No")

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL_NAME,
            "prompt": (
                f"Job application for Tanay Tammineni.\n"
                f"ABOUT: {CANDIDATE_BIO}\n"
                f"JOB: {job_title} at {company}\n"
                f"JD: {jd_snip[:400]}\n"
                f'QUESTION: "{question}"\n'
                f"2-4 sentences, max 80 words. No visa/OPT/H1B mentions. Answer only."
            ),
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 1200},
        }, timeout=45)
        if r.status_code == 200:
            return c(r.json().get("response", "").strip())
    except Exception:
        pass
    return c("")

# ─────────────────────────────────────────────────────────────────────────────
# BASE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class ATSHandler(ABC):
    """
    Base class for all ATS handlers.
    Subclasses override apply() for platform-specific logic.
    Common fill methods available to all handlers.
    """

    def __init__(self, page, ctx, url, res_pdf, cl_pdf, job_dir,
                 company, title, jd_text):
        self.page     = page
        self.ctx      = ctx
        self.url      = url
        self.res_pdf  = res_pdf
        self.cl_pdf   = cl_pdf
        self.job_dir  = job_dir
        self.company  = company
        self.title    = title
        self.jd_text  = jd_text or ""
        self.cl_text  = load_cl_text(job_dir)
        self.jd_snip  = self.jd_text[:500]
        self.why_us   = self._build_why_us()
        # find best frame (handles iframe embedding)
        self.frame, _ = find_frame_with_form(page)

    def _build_why_us(self):
        if self.cl_text:
            paras = [p.strip() for p in re.split(r"\s{3,}", self.cl_text) if len(p.strip()) > 20]
            if len(paras) > 1:
                return paras[1][:600]
            if paras:
                return paras[0][:600]
        return (
            f"My production LLM and RAG engineering experience directly aligns with "
            f"{self.company}'s needs. I built a distributed fine-tuning pipeline "
            f"achieving 41.2% per-GPU memory reduction and a hybrid RAG system with "
            f"23.7% faithfulness improvement."
        )

    @abstractmethod
    def apply(self) -> bool:
        """Navigate to form, fill it, submit. Returns True if submitted."""
        pass

    # ── Core fill primitives ─────────────────────────────────────────────────

    def fill(self, selector, value, frame=None):
        """
        Fill a text input using native Playwright with force=True.
        Bypasses sticky headers that intercept triple_click().
        """
        if not value:
            return False
        f = frame or self.frame
        # primary: force fill (bypasses overlay intercept)
        try:
            loc = f.locator(selector).first
            loc.wait_for(state="visible", timeout=3000)
            loc.scroll_into_view_if_needed()
            loc.fill(str(value), force=True)
            return True
        except Exception:
            pass
        # fallback: force click → keyboard clear → press_sequentially with human delay
        try:
            loc = f.locator(selector).first
            loc.wait_for(state="visible", timeout=2000)
            loc.scroll_into_view_if_needed()
            loc.click(force=True)
            loc.press("Control+A")
            loc.press("Backspace")
            loc.press_sequentially(str(value), delay=_human_delay())
            return True
        except Exception:
            return False

    def fill_by_label(self, label_text, value, frame=None):
        """Fill input by its label text using force=True."""
        if not value:
            return False
        f = frame or self.frame
        for exact in [True, False]:
            try:
                loc = f.get_by_label(label_text, exact=exact)
                if loc.count() > 0:
                    loc.first.wait_for(state="visible", timeout=2000)
                    tag = loc.first.evaluate("e => e.tagName.toLowerCase()")
                    if tag in ("input", "textarea"):
                        loc.first.scroll_into_view_if_needed()
                        loc.first.fill(str(value), force=True)
                        return True
            except Exception:
                pass
        return False

    def fill_by_placeholder(self, placeholder, value, frame=None):
        """Fill input by placeholder text using force=True."""
        if not value:
            return False
        f = frame or self.frame
        try:
            loc = f.get_by_placeholder(placeholder, exact=False)
            if loc.count() > 0:
                loc.first.wait_for(state="visible", timeout=2000)
                loc.first.scroll_into_view_if_needed()
                loc.first.fill(str(value), force=True)
                return True
        except Exception:
            return False

    def select_option(self, selector, options, frame=None):
        """Select from a native <select> element."""
        f = frame or self.frame
        for opt in options:
            try:
                f.locator(selector).first.select_option(label=opt)
                return True
            except Exception:
                try:
                    f.locator(selector).first.select_option(value=opt)
                    return True
                except Exception:
                    continue
        return False

    def select_by_label(self, label_text, options, frame=None):
        """
        Universal dropdown selector. Tries four strategies in order:
        1. Native <select> with force=True
        2. Select2 (Greenhouse uses this) — click container, pick option
        3. React-Select / Radix combobox — click control, pick option
        4. Keyboard navigation — type to filter, Enter to select
        """
        f = frame or self.frame

        # ── Strategy 1: native <select> ──────────────────────────────────────
        for exact in [True, False]:
            try:
                loc = f.get_by_label(label_text, exact=exact)
                if loc.count() > 0:
                    tag = loc.first.evaluate("e => e.tagName.toLowerCase()")
                    if tag == "select":
                        for opt in options:
                            try:
                                loc.first.select_option(label=opt, force=True)
                                return True
                            except Exception:
                                try:
                                    loc.first.select_option(value=opt, force=True)
                                    return True
                                except Exception:
                                    continue
            except Exception:
                pass

        # ── Strategy 2 & 3: find label element, locate nearby dropdown trigger ──
        trigger = self._find_dropdown_trigger(label_text, f)
        if trigger:
            # click to open
            try:
                trigger.scroll_into_view_if_needed()
                trigger.click(force=True)
                f.wait_for_timeout(600)
            except Exception:
                pass

            # try clicking a matching option in the opened list
            for opt in options:
                for sel in [
                    f'[role="option"]:has-text("{opt}")',
                    f'.select2-results__option:has-text("{opt}")',
                    f'li:has-text("{opt}")',
                    f'div[class*="option"]:has-text("{opt}")',
                    f'div[class*="item"]:has-text("{opt}")',
                    f'[class*="MenuList"] div:has-text("{opt}")',
                ]:
                    try:
                        oe = f.locator(sel).first
                        if oe.count() > 0 and oe.is_visible(timeout=800):
                            oe.click()
                            f.wait_for_timeout(300)
                            return True
                    except Exception:
                        continue

            # close if nothing matched
            try:
                f.keyboard.press("Escape")
            except Exception:
                pass

        # ── Strategy 4: keyboard navigation ──────────────────────────────────
        trigger2 = self._find_dropdown_trigger(label_text, f)
        if trigger2:
            try:
                trigger2.click(force=True)
                f.wait_for_timeout(400)
                f.keyboard.type(options[0][:6], delay=30)
                f.wait_for_timeout(400)
                f.keyboard.press("Enter")
                return True
            except Exception:
                pass

        return False

    def _find_dropdown_trigger(self, label_text, frame):
        """
        Given a label string, find the nearest clickable dropdown trigger element.
        Covers Select2, React-Select, Radix, and plain div[role=combobox].
        """
        f = frame
        TRIGGER_SELS = [
            '[role="combobox"]',
            '[class*="select2-selection"]',
            '[class*="Select__control"]',
            '[class*="select__control"]',
            '[class*="dropdown__control"]',
            '[class*="SelectTrigger"]',
            '.select2-container',
        ]

        # find all label elements matching the text
        try:
            for lbl in f.locator("label, legend, [class*='label'], [class*='Label']").all():
                try:
                    txt = lbl.inner_text().strip().lower()
                    if label_text.lower() not in txt and txt not in label_text.lower():
                        continue
                    # look for a trigger in the parent containers
                    for ts in TRIGGER_SELS:
                        try:
                            # search within progressively wider containers
                            for depth in range(1, 7):
                                ancestor_js = "el => {" + "let p=el;" + "p=p.parentElement;" * depth + "return p;}"
                                try:
                                    container = lbl.evaluate_handle(ancestor_js)
                                    t = f.locator(ts).first
                                    # verify trigger is near the label
                                    if t.count() > 0 and t.is_visible(timeout=400):
                                        return t
                                except Exception:
                                    pass
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass

        # fallback: find any trigger near matching text node
        try:
            for ts in TRIGGER_SELS:
                triggers = f.locator(ts).all()
                for t in triggers:
                    try:
                        if not t.is_visible(timeout=300):
                            continue
                        nearby = t.evaluate("""el => {
                            let p = el.parentElement;
                            for (let i=0; i<8; i++) {
                                if (!p) break;
                                let labels = p.querySelectorAll('label,legend,[class*=\"label\"],[class*=\"Label\"]');
                                for (let l of labels) {
                                    if (l.innerText.trim().length > 2) return l.innerText.toLowerCase();
                                }
                                p = p.parentElement;
                            }
                            return '';
                        }""")
                        if label_text.lower() in nearby or nearby in label_text.lower():
                            return t
                    except Exception:
                        continue
        except Exception:
            pass

        return None

    def click_radio(self, question_pattern, answer_pattern, frame=None):
        """Click a radio button matching question + answer patterns."""
        f = frame or self.frame
        try:
            for radio in f.locator('input[type="radio"]').all():
                try:
                    if not radio.is_visible(timeout=300):
                        continue
                    nearby = radio.evaluate("""el => {
                        let lbl = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
                        if (lbl) return lbl.innerText.toLowerCase();
                        let p = el.parentElement;
                        for (let i = 0; i < 8; i++) {
                            if (!p) break;
                            let legend = p.querySelector('legend');
                            if (legend) return (legend.innerText + ' ' + (p.innerText||'')).toLowerCase();
                            let t = (p.innerText || '').trim();
                            if (t.length > 2) return t.toLowerCase();
                            p = p.parentElement;
                        }
                        return (el.value || '').toLowerCase();
                    }""")
                    val = (radio.get_attribute("value") or "").lower()
                    comb = nearby + " " + val
                    if (re.search(question_pattern, nearby, re.I) and
                            re.search(answer_pattern, comb, re.I)):
                        radio.click()
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def upload_file(self, selector, path, frame=None):
        """Upload file to a standard input[type=file]."""
        if not path:
            return False
        f = frame or self.frame
        try:
            f.locator(selector).first.set_input_files(path)
            return True
        except Exception:
            pass
        # try via file chooser dialog
        try:
            with self.page.expect_file_chooser(timeout=5000) as fc:
                f.locator(selector).first.click()
            fc.value.set_files(path)
            return True
        except Exception:
            return False

    def wait_for_form(self, timeout=10000, frame=None):
        """Wait until at least 3 visible inputs appear."""
        f = frame or self.frame
        try:
            f.wait_for_selector(
                'input:not([type="hidden"])',
                state="visible",
                timeout=timeout
            )
            return True
        except Exception:
            return False

    def fill_open_questions(self, frame=None):
        """Fill textarea open questions using Ollama."""
        f = frame or self.frame
        cl_answer = self.cl_text[:1200] if self.cl_text else self.why_us
        ANSWERS = [
            (r"cover\s*letter",                                          cl_answer),
            (r"why.{0,50}(company|role|position|join|interest|us\b)",   self.why_us),
            (r"tell.{0,20}(about yourself|background)|introduce",        cl_answer[:600]),
            (r"what.{0,30}(excite|interest|draw|attract|motivat)",       self.why_us[:500]),
            (r"additional.{0,30}(info|comment)|anything\s*else",         self.why_us[:400]),
            (r"how.{0,30}(contribute|add\s*value|help)",                 self.why_us[:500]),
            (r"strength|qualification|relevant.*experience",              self.why_us[:400]),
        ]
        SKIP = ["captcha", "csrf", "token", "honeypot", "accommodat", "promo"]
        try:
            for ta in f.locator("textarea").all():
                try:
                    if not ta.is_visible(timeout=300):
                        continue
                    try:
                        cur = ta.input_value()
                        if cur and len(cur.strip()) > 15:
                            continue
                    except Exception:
                        pass
                    # get label
                    label = ""
                    ta_id = ta.get_attribute("id") or ""
                    if ta_id:
                        try:
                            lbl = f.locator(f'label[for="{ta_id}"]').first
                            if lbl.count() > 0:
                                label = lbl.inner_text().strip()
                        except Exception:
                            pass
                    if not label:
                        label = (ta.get_attribute("aria-label") or
                                 ta.get_attribute("placeholder") or
                                 ta.get_attribute("name") or "")
                    ll = label.lower()
                    if any(s in ll for s in SKIP):
                        continue
                    filled = False
                    for pat, ans in ANSWERS:
                        if re.search(pat, ll, re.I) and ans:
                            ta.click()
                            ta.fill(ans)
                            filled = True
                            break
                    if not filled and len(label) > 8:
                        print(f"      Ollama: '{label[:55]}'...")
                        ans = ask_ollama(label, self.company, self.title,
                                         self.jd_snip, self.cl_text)
                        if ans and len(ans) > 5:
                            ta.click()
                            ta.fill(ans[:800])
                except Exception:
                    continue
        except Exception:
            pass

    def fill_via_accessibility_tree(self, frame=None):
        """
        Universal fallback using Playwright's Accessibility Tree.
        Parses the semantic DOM (screen-reader view) — works on ANY website
        regardless of CSS framework, React version, or obfuscated class names.
        Maps candidate info to nodes by their accessible name/role,
        then executes fill/click/select actions on those node IDs.
        """
        f = frame or self.frame
        try:
            # Get the accessibility snapshot — clean semantic JSON
            snapshot = self.page.accessibility.snapshot(interesting_only=True)
            if not snapshot:
                return
        except Exception:
            return

        # candidate data to match against accessible names
        FILL_MAP = {
            "first name":    INFO["first"],
            "last name":     INFO["last"],
            "full name":     INFO["full"],
            "email":         INFO["email"],
            "phone":         INFO["phone_i"],
            "linkedin":      INFO["linkedin"],
            "github":        INFO["github"],
            "website":       INFO["portfolio"],
            "portfolio":     INFO["portfolio"],
            "school":        INFO["university"],
            "university":    INFO["university"],
            "college":       INFO["university"],
            "city":          INFO["city"],
            "zip":           INFO["zip"],
            "salary":        INFO["salary"],
        }
        SELECT_MAP = {
            "gender":        "Male",
            "hispanic":      "No",
            "race":          "Asian",
            "veteran":       "I am not a protected veteran",
            "disability":    "No, I do not have a disability",
            "degree":        "Master's",
            "country":       "United States",
            "state":         "Texas",
            "relocate":      "Yes",
            "sponsor":       "No",
            "authorized":    "Yes",
        }

        def walk(node, depth=0):
            if not node or depth > 15:
                return
            name  = (node.get("name") or "").lower().strip()
            role  = (node.get("role") or "").lower()
            value = node.get("value") or ""

            # skip already-filled nodes
            if value and len(str(value).strip()) > 1:
                for child in (node.get("children") or []):
                    walk(child, depth + 1)
                return

            # fill text inputs
            if role in ("textbox", "searchbox") and name:
                for kw, val in FILL_MAP.items():
                    if kw in name:
                        try:
                            loc = f.get_by_role("textbox", name=name, exact=False).first
                            if loc.count() > 0 and loc.is_visible(timeout=500):
                                loc.fill(str(val), force=True)
                        except Exception:
                            pass
                        break

            # handle comboboxes (Select2, React-Select, Radix)
            if role in ("combobox", "listbox") and name:
                for kw, val in SELECT_MAP.items():
                    if kw in name:
                        try:
                            # try native select first
                            loc = f.get_by_role("combobox", name=name, exact=False).first
                            if loc.count() > 0:
                                tag = loc.evaluate("e => e.tagName.toLowerCase()")
                                if tag == "select":
                                    loc.select_option(label=val, force=True)
                                else:
                                    # custom dropdown — click open then pick option
                                    loc.click(force=True)
                                    f.wait_for_timeout(500)
                                    opt_loc = f.locator(
                                        f'[role="option"]:has-text("{val}"), '
                                        f'li:has-text("{val}"), '
                                        f'div[class*="option"]:has-text("{val}")'
                                    ).first
                                    if opt_loc.count() > 0 and opt_loc.is_visible(timeout=800):
                                        opt_loc.click()
                                    else:
                                        f.keyboard.type(val[:5], delay=25)
                                        f.wait_for_timeout(300)
                                        f.keyboard.press("Enter")
                        except Exception:
                            pass
                        break

            for child in (node.get("children") or []):
                walk(child, depth + 1)

        walk(snapshot)

    def fill_standard_dropdowns(self, frame=None):
        """Fill common dropdowns by label."""
        f = frame or self.frame
        DROPDOWN_RULES = [
            (["Are you legally authorized","Authorized to work","Work Authorization",
              "Legally authorized to work in the United States",
              "authorized to work in the US", "authorized to work in the us now"],
             ["Yes","Yes, I am authorized","Authorized"]),
            (["Require sponsorship","Visa sponsorship","Will you require",
              "Sponsorship","without sponsorship","sponsorship transfers",
              "visa sponsorship now or in the future"],
             ["No","No, I do not require","Not required"]),
            (["State","State / Province","Province"],
             ["Texas","TX"]),
            (["Country","Country of Residence"],
             ["United States","United States of America","USA"]),
            (["Degree","Degree Level","Education Level","Highest Education"],
             ["Master","Master's","Master's Degree","M.S.","Graduate"]),
            (["Gender","Sex"],
             ["Male","Man","He/Him"]),
            (["Hispanic","Ethnicity","Hispanic/Latino"],
             ["No","Not Hispanic or Latino","Decline"]),
            (["Race"],
             ["Asian","Asian (Not Hispanic or Latino)"]),
            (["Veteran","Veteran Status","Protected Veteran"],
             ["I am not a protected veteran","Not a protected veteran",
              "No","I choose not to self-identify"]),
            (["Disability","Disability Status"],
             ["No, I do not have a disability","No",
              "I don't have a disability","I choose not to self-identify"]),
            (["Relocate","Willing to relocate","Relocation",
              "willing to relocate on your own","located in the greater",
              "located in the boston","located in"],
             ["Yes","Open to relocation","Willing","Yes, I am willing to relocate"]),
        ]
        for labels, options in DROPDOWN_RULES:
            for label in labels:
                if self.select_by_label(label, options, frame=f):
                    break

    def fill_standard_radios(self, frame=None):
        """Fill common radio button groups."""
        RADIO_RULES = [
            (r"authorized|legally.*work|eligible.*work|work.*auth",
             r"\byes\b|authorized|eligible|i am"),
            (r"require.*sponsor|visa|h.?1.?b|sponsorship",
             r"\bno\b|not require|do not"),
            (r"reloca|willing to move",
             r"\byes\b|willing|open"),
            (r"\bgender\b|\bsex\b",
             r"\bmale\b|\bman\b"),
            (r"hispanic|latino",
             r"\bno\b|not hispanic|decline"),
            (r"\brace\b|racial",
             r"\basian\b"),
            (r"veteran|military status",
             r"not a protected|not a veteran|i am not|\bno\b"),
            (r"disability|disabled",
             r"\bno\b|do not have|don.t have|decline"),
        ]
        for q_pat, a_pat in RADIO_RULES:
            self.click_radio(q_pat, a_pat, frame=frame or self.frame)

    def fill_standard_checkboxes(self, frame=None):
        """Check agreement/terms checkboxes."""
        f = frame or self.frame
        try:
            for cb in f.locator('input[type="checkbox"]').all():
                try:
                    if not cb.is_visible(timeout=300):
                        continue
                    nearby = cb.evaluate("""el => {
                        let lbl = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
                        if (lbl) return lbl.innerText.toLowerCase();
                        return (el.parentElement || {innerText: ''}).innerText.toLowerCase();
                    }""")
                    if re.search(r"agree|certif|confirm|terms|accept|acknowledge|consent",
                                 nearby, re.I):
                        if not cb.is_checked():
                            cb.click()
                except Exception:
                    continue
        except Exception:
            pass

    def fill_yesno_toggles(self, frame=None):
        """Handle Workable-style YES/NO button toggles."""
        f = frame or self.frame
        NO_PATTERNS = [
            r"require.*sponsor|visa.*sponsor|h.?1.?b|sponsorship",
            r"u\.?s\.? citizen|naturalized.*citizen|permanent resident",
            r"currently based in (san diego|boston|new york|chicago|seattle|austin|dallas)",
        ]
        YES_PATTERNS = [
            r"authorized|legally.*work|eligible.*work",
            r"reloca|willing to move",
        ]
        try:
            containers = f.locator(
                '*:has(button:has-text("YES")):has(button:has-text("NO"))'
            ).all()
            for container in containers[:15]:
                try:
                    ctx_text = container.inner_text().lower()
                    answer = None
                    for pat in NO_PATTERNS:
                        if re.search(pat, ctx_text, re.I):
                            answer = "NO"
                            break
                    if answer is None:
                        for pat in YES_PATTERNS:
                            if re.search(pat, ctx_text, re.I):
                                answer = "YES"
                                break
                    if not answer:
                        continue
                    btn = container.locator(
                        f'button:has-text("{answer}")'
                    ).first
                    if btn.count() > 0 and btn.is_visible(timeout=500):
                        btn.click()
                except Exception:
                    continue
        except Exception:
            pass

    def check_confirmation(self):
        try:
            txt = self.page.locator("body").inner_text().lower()
            return any(x in txt for x in [
                "application submitted", "application received",
                "thank you for applying", "thanks for applying",
                "successfully submitted", "successfully applied",
                "we've received your application", "application complete",
                "you have applied",
            ])
        except Exception:
            return False

    def is_expired(self):
        try:
            txt = self.page.locator("body").inner_text().lower()
            return any(x in txt for x in [
                "job has been filled", "no longer accepting", "posting has expired",
                "job is no longer available", "this job is closed", "position has been filled",
            ])
        except Exception:
            return False

# ─────────────────────────────────────────────────────────────────────────────
# GREENHOUSE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class GreenhouseHandler(ATSHandler):
    """
    Greenhouse uses known, stable field IDs.
    Form is always on the same page — no Apply button needed.
    """

    def apply(self) -> bool:
        page = self.page
        f    = self.frame

        # Step 1: click Apply button — Greenhouse job boards show description first,
        # the actual form is below or requires clicking Apply to reveal it
        try:
            apply_btn = page.locator(
                'a:has-text("Apply for this job"), '
                'button:has-text("Apply for this job"), '
                'a:has-text("Apply"), '
                'button:has-text("Apply")'
            ).first
            if apply_btn.is_visible(timeout=3000):
                print("  Clicking Apply button...")
                apply_btn.click()
                page.wait_for_timeout(1500)
        except Exception:
            pass

        # Step 2: wait for #first_name to be visible (form is now in viewport)
        try:
            f.wait_for_selector("#first_name", state="visible", timeout=10000)
        except Exception:
            # check iframes
            self.frame, _ = find_frame_with_form(page)
            f = self.frame
            try:
                f.wait_for_selector("#first_name", state="visible", timeout=5000)
            except Exception:
                print("  Form not found after clicking Apply")
                return False

        if self.is_expired():
            print("  → Expired/closed posting")
            return False

        print("  Filling Greenhouse form...")

        # Step 3: file uploads
        if self.res_pdf:
            try:
                f.wait_for_selector("#resume", state="attached", timeout=5000)
                f.locator("#resume").set_input_files(self.res_pdf)
                print("    ✓ Resume uploaded")
            except Exception:
                self._upload_via_chooser(f, self.res_pdf, "resume")

        if self.cl_pdf:
            try:
                f.wait_for_selector("#cover_letter", state="attached", timeout=3000)
                f.locator("#cover_letter").set_input_files(self.cl_pdf)
                print("    ✓ Cover letter uploaded")
            except Exception:
                pass

        # Step 4: fill fields, track success
        filled_any = False

        if self.fill("#first_name", INFO["first"],   frame=f): filled_any = True
        if self.fill("#last_name",  INFO["last"],    frame=f): filled_any = True
        if self.fill("#email",      INFO["email"],   frame=f): filled_any = True
        if self.fill("#phone",      INFO["phone_i"], frame=f): filled_any = True

        # Standard Greenhouse URL fields (urls[] pattern)
        for name, val in [
            ("urls[LinkedIn]",  INFO["linkedin"]),
            ("urls[GitHub]",    INFO["github"]),
            ("urls[Portfolio]", INFO["portfolio"]),
            ("urls[Website]",   INFO["portfolio"]),
        ]:
            if self.fill(f'input[name="{name}"]', val, frame=f):
                filled_any = True

        # Fallbacks for recruiters who use custom fields instead of standard ones
        if self.fill_by_label("LinkedIn Profile", INFO["linkedin"],  frame=f): filled_any = True
        if self.fill_by_label("LinkedIn",         INFO["linkedin"],  frame=f): filled_any = True
        if self.fill_by_label("Website",          INFO["portfolio"], frame=f): filled_any = True
        if self.fill_by_label("GitHub",           INFO["github"],    frame=f): filled_any = True
        if self.fill_by_label("School",           INFO["university"],frame=f): filled_any = True
        if self.fill_by_label("Degree",           INFO["degree_s"],  frame=f): filled_any = True

        self.fill_by_placeholder("City, State, Country", INFO["location"], frame=f)
        self.fill_by_label("Location", INFO["location"], frame=f)

        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)
        self.fill_standard_checkboxes(frame=f)
        self.fill_open_questions(frame=f)

        # Scroll down and second pass — catches lazy-loaded fields
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
            page.wait_for_timeout(800)
        except Exception:
            pass

        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)

        # Scroll to bottom for EEO section
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(600)
        except Exception:
            pass

        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)

        # Accessibility tree — universal fallback for any missed dropdowns
        self.fill_via_accessibility_tree(frame=f)

        if not filled_any:
            print("  No fields were filled — form may be blocked or hidden")
            return False

        return True

    def _upload_via_chooser(self, frame, path, field_type):
        """Fallback: click the upload button and catch the file chooser."""
        try:
            sel = f'button:has-text("Upload {field_type.title()}")'
            with self.page.expect_file_chooser(timeout=5000) as fc:
                frame.locator(sel).first.click()
            fc.value.set_files(path)
            print(f"    ✓ {field_type.title()} uploaded via chooser")
        except Exception:
            pass

    def apply_via_api(self) -> bool:
        """
        Protocol Paradigm: intercept Greenhouse network traffic to get job_id
        and session tokens, then POST the application directly to the API.
        Bypasses the UI entirely — works even when form elements are blocked.
        """
        page = self.page
        captured = {"job_id": None, "token": None}

        # intercept requests to capture job_id and auth tokens
        def on_request(req):
            u = req.url
            if "greenhouse.io" in u and "/applications" in u:
                try:
                    captured["token"] = req.headers.get("x-csrf-token") or \
                                        req.headers.get("authorization", "")
                except Exception:
                    pass

        page.on("request", on_request)

        # extract job_id from URL
        m = re.search(r"/jobs/(\d+)", self.url)
        if not m:
            return False
        job_id = m.group(1)

        # extract board token from URL (e.g. greenhouse.io/racapitalmanagementllc/...)
        m2 = re.search(r"greenhouse\.io/([^/]+)/", self.url)
        board_token = m2.group(1) if m2 else ""

        if not board_token:
            return False

        # build multipart form — matches Greenhouse API schema
        try:
            api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}/applications"

            with open(self.res_pdf, "rb") as rf:
                resume_bytes = rf.read()

            payload = {
                "first_name":   INFO["first"],
                "last_name":    INFO["last"],
                "email":        INFO["email"],
                "phone":        INFO["phone_i"],
                "job_id":       job_id,
                "mapped_url_greenhouse_website":   INFO["portfolio"],
                "mapped_url_linkedin":             INFO["linkedin"],
                "mapped_url_github":               INFO["github"],
            }

            cookies = {c["name"]: c["value"]
                       for c in page.context.cookies()}
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": self.url,
                "Origin":  "https://job-boards.greenhouse.io",
            }

            files = {
                "resume": ("resume.pdf", resume_bytes, "application/pdf"),
            }

            resp = requests.post(
                api_url,
                data=payload,
                files=files,
                headers=headers,
                cookies=cookies,
                timeout=30,
            )

            if resp.status_code in (200, 201):
                print(f"    ✓ API submission successful (HTTP {resp.status_code})")
                return True
            else:
                print(f"    API returned {resp.status_code} — falling back to UI")
                return False

        except Exception as e:
            print(f"    API attempt failed: {e}")
            return False

# ─────────────────────────────────────────────────────────────────────────────
# LEVER HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class LeverHandler(ATSHandler):
    """
    Lever uses a single-page form with name= attributes.
    Full name in one field (not split).
    """

    def apply(self) -> bool:
        f = self.frame

        try:
            f.wait_for_selector('.application-form', state="visible", timeout=15000)
        except Exception:
            self.frame, _ = find_frame_with_form(self.page)
            f = self.frame

        if self.is_expired():
            return False

        print("  Filling Lever form...")

        # Lever file upload
        if self.res_pdf:
            try:
                with self.page.expect_file_chooser(timeout=5000) as fc:
                    f.locator('button:has-text("Upload resume")').first.click()
                fc.value.set_files(self.res_pdf)
                print("    ✓ Resume uploaded")
            except Exception:
                self.fill('input[type="file"]', self.res_pdf, frame=f)

        # Lever uses full name in one field
        self.fill('input[name="name"]',    INFO["full"],    frame=f)
        self.fill('input[name="email"]',   INFO["email"],   frame=f)
        self.fill('input[name="phone"]',   INFO["phone_i"], frame=f)
        self.fill('input[name="org"]',     INFO["company"], frame=f)

        # Lever links
        for name, val in [
            ("urls[LinkedIn]",   INFO["linkedin"]),
            ("urls[GitHub]",     INFO["github"]),
            ("urls[Portfolio]",  INFO["portfolio"]),
            ("urls[Other]",      INFO["portfolio"]),
        ]:
            self.fill(f'input[name="{name}"]', val, frame=f)

        self.fill_by_label("Location", INFO["location"], frame=f)
        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)
        self.fill_standard_checkboxes(frame=f)
        self.fill_open_questions(frame=f)
        return True

# ─────────────────────────────────────────────────────────────────────────────
# WORKABLE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class WorkableHandler(ATSHandler):
    """
    Workable: Apply Now button opens a modal (same-page overlay).
    Uses JS click to avoid overlay blocking.
    """

    def apply(self) -> bool:
        page = self.page

        # click Apply Now via JS (avoids overlay detection issues)
        clicked = page.evaluate("""() => {
            const pats = [/^apply now$/i, /^apply for this job$/i, /apply now/i, /^apply$/i];
            const btns = [...document.querySelectorAll('button, a')];
            for (const pat of pats) {
                const b = btns.find(el =>
                    pat.test((el.innerText || el.textContent || '').trim()) && !el.disabled
                );
                if (b) { b.click(); return true; }
            }
            return false;
        }""")

        if not clicked:
            print("  No Apply Now button on Workable page")
            return False

        print("  Apply Now clicked — waiting for modal...")

        # wait for modal inputs
        try:
            page.wait_for_selector('input[name="firstname"]', state="visible", timeout=10000)
            f = page
        except Exception:
            self.frame, _ = find_frame_with_form(page)
            f = self.frame

        if not self.wait_for_form(timeout=5000, frame=f):
            return False

        print("  Filling Workable form...")

        # resume
        if self.res_pdf:
            try:
                with page.expect_file_chooser(timeout=5000) as fc:
                    f.locator('button:has-text("CV"),'
                              'button:has-text("Resume"),'
                              'button:has-text("Upload")').first.click()
                fc.value.set_files(self.res_pdf)
                print("    ✓ Resume uploaded")
            except Exception:
                pass

        # Workable uses firstname/lastname name attributes
        for name, val in [
            ("firstname",  INFO["first"]),
            ("lastname",   INFO["last"]),
            ("email",      INFO["email"]),
            ("phone",      INFO["phone_i"]),
            ("headline",   INFO["title"]),
            ("summary",    self.why_us[:400]),
            ("address",    INFO["location"]),
        ]:
            self.fill(f'input[name="{name}"], textarea[name="{name}"]', val, frame=f)

        # Workable social links
        for placeholder, val in [
            ("LinkedIn",  INFO["linkedin"]),
            ("GitHub",    INFO["github"]),
            ("Portfolio", INFO["portfolio"]),
            ("Website",   INFO["portfolio"]),
        ]:
            self.fill_by_placeholder(placeholder, val, frame=f)

        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)
        self.fill_yesno_toggles(frame=f)
        self.fill_standard_checkboxes(frame=f)
        self.fill_open_questions(frame=f)

        # scroll modal and second pass
        try:
            page.evaluate("""() => {
                const m = document.querySelector(
                    '[role="dialog"], [class*="modal"], [class*="Modal"]'
                );
                if (m) m.scrollTop = m.scrollHeight / 2;
            }""")
            page.wait_for_timeout(800)
        except Exception:
            pass

        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)
        self.fill_yesno_toggles(frame=f)
        self.fill_open_questions(frame=f)

        # auto-submit
        submitted = page.evaluate("""() => {
            const b = [...document.querySelectorAll('button')].find(el =>
                /^submit application$|^submit$/i.test((el.innerText || '').trim())
            );
            if (b) { b.click(); return true; }
            return false;
        }""")
        if submitted:
            print("    → Workable submitted automatically")
        return True

# ─────────────────────────────────────────────────────────────────────────────
# SMARTRECRUITERS HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class SmartRecruitersHandler(ATSHandler):
    """SmartRecruiters: navigate to {url}/apply, click 'I'm interested' button."""

    def apply(self) -> bool:
        apply_url = self.url.split("?")[0].rstrip("/") + "/apply"
        self.page.goto(apply_url, timeout=30000, wait_until="domcontentloaded")
        self.page.wait_for_timeout(2000)

        # SmartRecruiters shows "I'm interested" as the Apply button
        for sel in [
            'button:has-text("I\'m interested")',
            'a:has-text("I\'m interested")',
            'button:has-text("Apply")',
            'a:has-text("Apply")',
        ]:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    print(f"    → Clicking: {sel[:40]}")
                    btn.click(force=True)
                    try:
                        self.page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        self.page.wait_for_timeout(3000)
                    break
            except Exception:
                continue

        try:
            self.page.wait_for_selector(
                'input[name="firstName"], input[id*="firstName"], '
                'input[placeholder*="First"]',
                state="visible", timeout=10000
            )
        except Exception:
            self.frame, _ = find_frame_with_form(self.page)

        f = self.frame
        if self.is_expired():
            return False

        print("  Filling SmartRecruiters form...")

        if self.res_pdf:
            try:
                with self.page.expect_file_chooser(timeout=4000) as fc:
                    f.locator(
                        'button:has-text("Resume"), button:has-text("CV"), '
                        'button:has-text("Upload")'
                    ).first.click()
                fc.value.set_files(self.res_pdf)
                print("    ✓ Resume uploaded")
            except Exception:
                try:
                    f.wait_for_selector('input[type="file"]', state="attached", timeout=3000)
                    f.locator('input[type="file"]').first.set_input_files(self.res_pdf)
                    print("    ✓ Resume uploaded")
                except Exception:
                    pass

        for sel, val in [
            ('input[name="firstName"], input[id*="firstName"]', INFO["first"]),
            ('input[name="lastName"],  input[id*="lastName"]',  INFO["last"]),
            ('input[name="email"],     input[id*="email"]',     INFO["email"]),
            ('input[name="phone"],     input[id*="phone"]',     INFO["phone_i"]),
        ]:
            self.fill(sel, val, frame=f)

        self.fill_by_label("LinkedIn",  INFO["linkedin"],  frame=f)
        self.fill_by_label("Portfolio", INFO["portfolio"], frame=f)
        self.fill_by_label("GitHub",    INFO["github"],    frame=f)

        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)
        self.fill_standard_checkboxes(frame=f)
        self.fill_open_questions(frame=f)
        return True

# ─────────────────────────────────────────────────────────────────────────────
# ASHBY HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class AshbyHandler(ATSHandler):
    """Ashby: navigate to {url}/apply directly."""

    def apply(self) -> bool:
        apply_url = self.url.split("?")[0].rstrip("/") + "/apply"
        self.page.goto(apply_url, timeout=30000, wait_until="domcontentloaded")

        try:
            self.page.wait_for_selector('input[placeholder*="First"]',
                                        state="visible", timeout=10000)
        except Exception:
            self.frame, _ = find_frame_with_form(self.page)

        f = self.frame
        print("  Filling Ashby form...")

        if self.res_pdf:
            try:
                with self.page.expect_file_chooser(timeout=5000) as fc:
                    f.locator('button:has-text("Upload"), button:has-text("Resume")').first.click()
                fc.value.set_files(self.res_pdf)
                print("    ✓ Resume uploaded")
            except Exception:
                pass

        self.fill_by_placeholder("First Name", INFO["first"],   frame=f)
        self.fill_by_placeholder("Last Name",  INFO["last"],    frame=f)
        self.fill_by_placeholder("Email",      INFO["email"],   frame=f)
        self.fill_by_placeholder("Phone",      INFO["phone_i"], frame=f)
        self.fill_by_placeholder("LinkedIn",   INFO["linkedin"],frame=f)
        self.fill_by_placeholder("Website",    INFO["portfolio"],frame=f)
        self.fill_by_placeholder("GitHub",     INFO["github"],  frame=f)

        self.fill_standard_dropdowns(frame=f)
        self.fill_standard_radios(frame=f)
        self.fill_standard_checkboxes(frame=f)
        self.fill_open_questions(frame=f)
        return True

# ─────────────────────────────────────────────────────────────────────────────
# GENERIC HANDLER — fallback for unknown ATS
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# WORKDAY HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class WorkdayHandler(ATSHandler):
    """
    Workday forces a 'Start Your Application' modal then an account wall.
    Strategy:
    1. Dismiss modal → 'Use My Last Application' > 'Apply Manually' > 'Autofill'
    2. Create Account wall → auto-generate account with standard password
    3. Sign In wall → sign in with existing credentials
    4. Multi-step fill with Next-button navigation (up to 8 steps)
    """

    STANDARD_PASSWORD = "JobAgent2026!@#"

    def apply(self) -> bool:
        page = self.page
        print("  Workday protocol...")

        # Step 1: dismiss "Start Your Application" modal
        modal_handled = False
        for sel, label in [
            ('button:has-text("Use My Last Application")', "Use My Last Application"),
            ('button:has-text("Apply Manually")',          "Apply Manually"),
            ('a:has-text("Apply Manually")',               "Apply Manually"),
            ('button:has-text("Autofill with Resume")',    "Autofill with Resume"),
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    print(f"    → Clicking: {label}")
                    btn.click(force=True)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        page.wait_for_timeout(3000)
                    modal_handled = True
                    break
            except Exception:
                continue

        if not modal_handled:
            try:
                btn = page.locator(
                    'button:has-text("Apply"), a:has-text("Apply")'
                ).first
                if btn.is_visible(timeout=3000):
                    btn.click(force=True)
                    page.wait_for_timeout(3000)
            except Exception:
                pass

        # Step 2: handle Create Account wall
        try:
            create_btn = page.locator(
                'button:has-text("Create Account"), a:has-text("Create Account")'
            ).first
            if create_btn.is_visible(timeout=4000):
                print("    → Account wall — creating account...")
                create_btn.click(force=True)
                page.wait_for_timeout(2000)

                self.fill_by_label("Email Address",       INFO["email"])
                self.fill_by_label("Password",            self.STANDARD_PASSWORD)
                self.fill_by_label("Verify New Password", self.STANDARD_PASSWORD)
                self.fill_by_label("Verify Password",     self.STANDARD_PASSWORD)
                self.fill_by_label("Confirm Password",    self.STANDARD_PASSWORD)

                # check Terms of Service / I Agree box
                try:
                    cb = page.locator('input[type="checkbox"]').first
                    if cb.is_visible(timeout=1000) and not cb.is_checked():
                        cb.click(force=True)
                except Exception:
                    pass

                # submit
                for sub_sel in [
                    'button:has-text("Create Account")',
                    'button:has-text("Create")',
                    'button[type="submit"]',
                ]:
                    try:
                        sub = page.locator(sub_sel).first
                        if sub.is_visible(timeout=1500):
                            sub.click(force=True)
                            try:
                                page.wait_for_load_state("networkidle", timeout=8000)
                            except Exception:
                                page.wait_for_timeout(4000)
                            print("    → Account created")
                            break
                    except Exception:
                        continue
        except Exception:
            pass

        # Step 3: handle Sign In wall (account already exists)
        try:
            signin_btn = page.locator('button:has-text("Sign In")').first
            if signin_btn.is_visible(timeout=3000):
                print("    → Sign In wall — signing in...")
                self.fill_by_label("Email Address", INFO["email"])
                self.fill_by_label("Password",      self.STANDARD_PASSWORD)
                signin_btn.click(force=True)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    page.wait_for_timeout(4000)
        except Exception:
            pass

        # Step 4: multi-step fill
        self.frame, n = find_frame_with_form(page)
        if n < 2:
            navigated = llm_popup_navigator(page, max_steps=3)
            if not navigated:
                return False
            self.frame, n = find_frame_with_form(page)

        if n < 2:
            return False

        f = self.frame
        print(f"  Filling Workday form ({n} inputs)...")

        for step_num in range(8):
            # file upload on step 1
            if step_num == 0 and self.res_pdf:
                try:
                    fi = f.locator('input[type="file"]').first
                    if fi.is_visible(timeout=2000):
                        fi.set_input_files(self.res_pdf)
                        print("    ✓ Resume uploaded")
                        page.wait_for_timeout(2000)
                except Exception:
                    pass

            self.fill_by_label("First Name",     INFO["first"],   frame=f)
            self.fill_by_label("Last Name",      INFO["last"],    frame=f)
            self.fill_by_label("Email Address",  INFO["email"],   frame=f)
            self.fill_by_label("Phone Number",   INFO["phone_i"], frame=f)
            self.fill_by_label("Address Line 1", INFO["street"],  frame=f)
            self.fill_by_label("City",           INFO["city"],    frame=f)
            self.fill_by_label("Postal Code",    INFO["zip"],     frame=f)
            self.fill_standard_dropdowns(frame=f)
            self.fill_standard_radios(frame=f)
            self.fill_open_questions(frame=f)
            self.fill_via_accessibility_tree(frame=f)

            # next or submit
            next_btn = None
            for sel in [
                'button:has-text("Next")',
                'button:has-text("Save and Continue")',
                'button[data-automation-id="bottom-navigation-next-button"]',
            ]:
                try:
                    b = f.locator(sel).first
                    if b.is_visible(timeout=1000):
                        next_btn = b; break
                except Exception:
                    continue

            if next_btn:
                print(f"    → Step {step_num + 1} → next")
                next_btn.evaluate("el => el.click()")
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    page.wait_for_timeout(2000)
                self.frame, _ = find_frame_with_form(page)
                f = self.frame
            else:
                # check for Submit
                try:
                    sub = f.locator('button:has-text("Submit")').first
                    if sub.is_visible(timeout=1000):
                        print("    → Submit button reached")
                except Exception:
                    pass
                break

        return True


class GenericHandler(ATSHandler):
    """
    Fallback handler. Finds Apply button, waits for form,
    fills using label-based detection.
    Uses multi-page navigation (Next button).
    """

    APPLY_SELECTORS = [
        'button:has-text("Apply for this job")',
        'a:has-text("Apply for this job")',
        'button:has-text("Apply Now")',
        'a:has-text("Apply Now")',
        'button:has-text("Apply now")',
        'a:has-text("Apply now")',
        '[data-ui="apply-button"]',
        '[data-qa="btn-apply"]',
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        '[class*="apply-button"]',
    ]

    NEXT_SELECTORS = [
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'button:has-text("Save and Continue")',
        'button:has-text("Next Step")',
    ]

    SUBMIT_SELECTORS = [
        'button:has-text("Submit Application")',
        'button:has-text("Submit My Application")',
        'button:has-text("Submit")',
        'input[type="submit"][value*="Submit"]',
    ]

    def apply(self) -> bool:
        page = self.page

        # check if form already on page
        _, n = find_frame_with_form(page)
        if n <= 3:
            # try clicking Apply button
            self._click_apply_button()
            # wait for form to load
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

        # update frame after navigation
        self.frame, n = find_frame_with_form(page)
        f = self.frame

        if n == 0:
            return False

        if self.is_expired():
            return False

        print(f"  Filling Generic form ({n} inputs)...")

        # multi-page filling loop
        MAX_PAGES = 8
        last_url  = ""
        for page_num in range(1, MAX_PAGES + 1):
            print(f"    Page {page_num}...")
            self._fill_page(f)

            kind, btn = self._get_next_or_submit(f)

            if kind == "next":
                print(f"    → Clicking Next ({page_num}→{page_num+1})")
                try:
                    btn.evaluate("el => el.click()")
                    try:
                        page.wait_for_load_state("networkidle", timeout=6000)
                    except Exception:
                        page.wait_for_timeout(2000)
                    new_url = page.url
                    if new_url == last_url:
                        print("    ! Page did not advance — stopping")
                        break
                    last_url = new_url
                    self.frame, _ = find_frame_with_form(page)
                    f = self.frame
                except Exception as e:
                    print(f"    ! Next click failed: {e}")
                    break

            elif kind == "submit":
                print(f"    → Submitting on page {page_num}")
                try:
                    btn.scroll_into_view_if_needed()
                    btn.evaluate("el => el.click()")
                    page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"    Submit click error: {e}")
                break

            else:
                break

        return True

    def _click_apply_button(self):
        page = self.page
        tabs_before = len(self.ctx.pages)
        page.evaluate("window.scrollTo(0, 400)")
        try:
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for sel in self.APPLY_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible(timeout=1500):
                    print(f"  Clicking: {sel[:55]}")
                    btn.evaluate("el => el.click()")
                    try:
                        page.wait_for_load_state("networkidle", timeout=7000)
                    except Exception:
                        page.wait_for_timeout(3000)
                    # new tab?
                    if len(self.ctx.pages) > tabs_before:
                        self.page = self.ctx.pages[-1]
                        self.page.bring_to_front()
                        page.wait_for_timeout(2000)
                    return
            except Exception:
                continue

    def _fill_page(self, frame):
        """Fill everything visible on current page."""
        if self.res_pdf:
            try:
                fi = frame.locator('input[type="file"]').first
                fi.wait_for(state="attached", timeout=3000)
                fi.set_input_files(self.res_pdf)
                print("    ✓ Resume uploaded")
            except Exception:
                pass

        # standard fields by label
        LABEL_FILLS = [
            (["First Name","Legal First Name","Given Name"], INFO["first"]),
            (["Last Name","Legal Last Name","Family Name"],  INFO["last"]),
            (["Full Name","Legal Name","Name"],              INFO["full"]),
            (["Email","Email Address"],                      INFO["email"]),
            (["Phone","Phone Number","Mobile"],              INFO["phone_i"]),
            (["LinkedIn","LinkedIn Profile"],                INFO["linkedin"]),
            (["GitHub","Github"],                           INFO["github"]),
            (["Website","Portfolio"],                        INFO["portfolio"]),
            (["City"],                                       INFO["city"]),
            (["Zip","Zip Code","Postal Code"],               INFO["zip"]),
            (["University","College","School"],              INFO["university"]),
            (["Degree","Field of Study","Major"],            INFO["degree_s"]),
            (["GPA"],                                        INFO["gpa"]),
            (["Salary","Desired Salary","Expected Salary"],  INFO["salary"]),
            (["Start Date","When can you start"],            INFO["start"]),
        ]
        for labels, value in LABEL_FILLS:
            for label in labels:
                if self.fill_by_label(label, value, frame=frame):
                    break

        self.fill_standard_dropdowns(frame=frame)
        self.fill_standard_radios(frame=frame)
        self.fill_yesno_toggles(frame=frame)
        self.fill_standard_checkboxes(frame=frame)
        self.fill_open_questions(frame=frame)

    def _get_next_or_submit(self, frame):
        for sel in self.NEXT_SELECTORS:
            try:
                btn = frame.locator(sel).first
                if btn.count() > 0 and btn.is_visible(timeout=600):
                    return "next", btn
            except Exception:
                continue
        for sel in self.SUBMIT_SELECTORS:
            try:
                btn = frame.locator(sel).first
                if btn.count() > 0 and btn.is_visible(timeout=600):
                    return "submit", btn
            except Exception:
                continue
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# MANUAL HANDLER — opens browser, you apply yourself
# ─────────────────────────────────────────────────────────────────────────────

class ManualHandler(ATSHandler):
    """For Oracle, Taleo, Google, Apple, Amazon — manual apply."""

    def apply(self) -> bool:
        print(f"\n  Manual portal — apply in browser")
        print(f"  Resume: {self.res_pdf}")
        if self.cl_pdf:
            print(f"  CL:     {self.cl_pdf}")
        return True  # always returns True — user confirms

# ─────────────────────────────────────────────────────────────────────────────
# LLM POPUP NAVIGATOR — agentic fallback for unknown modals/pop-ups
# ─────────────────────────────────────────────────────────────────────────────

def llm_popup_navigator(page, max_steps=4):
    """
    When the bot encounters an unknown modal or multi-step gateway,
    this reads the Accessibility Tree, asks Ollama what to click,
    and clicks it. Repeats up to max_steps times.

    Works on ANY website — no hardcoding required.
    The LLM reads the screen semantically, like a human would.
    """
    for step in range(max_steps):
        # check if we already have a form
        try:
            n = page.locator('input:not([type="hidden"])').count()
            if n >= 3:
                return True
        except Exception:
            pass

        # get accessibility tree — clean semantic view of the page
        try:
            snapshot = page.accessibility.snapshot(interesting_only=True)
            if not snapshot:
                continue
        except Exception:
            continue

        # extract all interactive node names (buttons, links)
        def collect_clickable(node, depth=0):
            if not node or depth > 10:
                return []
            items = []
            role = (node.get("role") or "").lower()
            name = (node.get("name") or "").strip()
            if role in ("button", "link", "menuitem") and name and len(name) < 80:
                items.append(name)
            for child in (node.get("children") or []):
                items.extend(collect_clickable(child, depth + 1))
            return items

        clickable = collect_clickable(snapshot)
        if not clickable:
            continue

        # ask Ollama which button to click
        prompt = (
            "I am a bot trying to apply for a job online.\n"
            f"The screen shows these clickable elements:\n{clickable[:30]}\n\n"
            "Which ONE should I click to proceed with the job application? "
            "Reply with ONLY the exact button/link text. "
            "Prefer: Apply, Apply Manually, Continue, Next, Start Application, Submit. "
            "Avoid: Sign In, Create Account, Cancel, Close, Back, Login."
        )
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_ctx": 800},
            }, timeout=30)
            if r.status_code != 200:
                continue
            answer = r.json().get("response", "").strip().strip('"').strip("'")
        except Exception:
            continue

        if not answer or len(answer) > 60:
            continue

        print(f"    LLM navigator: click '{answer}'")

        # click the suggested element
        clicked = False
        for sel in [
            f'button:has-text("{answer}")',
            f'a:has-text("{answer}")',
            f'[role="button"]:has-text("{answer}")',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        page.wait_for_timeout(2000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            print(f"    Could not find '{answer}' — stopping navigator")
            break

    # final check
    try:
        return page.locator('input:not([type="hidden"])').count() >= 3
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DISCOVERY ROUTER — handles landing pages, job indexes, multi-step navigation
# ─────────────────────────────────────────────────────────────────────────────

def resolve_careers_landing_page(page, ctx, target_title=""):
    """
    Intelligent Router: if the URL lands on a corporate splash page
    (e.g. gumgum.com/jobs, flatiron.com/careers) instead of an ATS form,
    this function clicks through to find the actual application.

    Flow:
    1. Already on form? → return (page, True) immediately
    2. On a job listings index? → find and click the specific role title
    3. On a splash page? → click "View Open Positions" / "See Roles" etc.
    4. Opened a new tab? → switch to it
    """
    def input_count(p):
        try:
            return p.locator('input:not([type="hidden"])').count()
        except Exception:
            return 0

    # already on form
    if input_count(page) >= 3:
        return page, True

    print("  [?] Landing page detected — running discovery route...")

    # ── Step 1: look for the specific job title link (listings index) ─────────
    if target_title:
        for attempt in [target_title, target_title.split("-")[0].strip(),
                        target_title.split("–")[0].strip()]:
            try:
                link = page.locator(f'a:has-text("{attempt}")').first
                if link.count() == 0:
                    link = page.locator(f'[role="link"]:has-text("{attempt}")').first
                if link.count() > 0 and link.is_visible(timeout=2000):
                    tabs_before = len(ctx.pages)
                    print(f"    → Clicking job listing: '{attempt}'")
                    link.click(force=True)
                    try:
                        page.wait_for_load_state("networkidle", timeout=6000)
                    except Exception:
                        page.wait_for_timeout(3000)
                    if len(ctx.pages) > tabs_before:
                        page = ctx.pages[-1]
                        page.bring_to_front()
                        page.wait_for_timeout(2000)
                    if input_count(page) >= 3:
                        return page, True
            except Exception:
                continue

    # ── Step 2: click "View Open Positions" / "Explore Careers" etc. ─────────
    DISCOVERY_SELECTORS = [
        'a:has-text("View Open Positions")',   'button:has-text("View Open Positions")',
        'a:has-text("See Open Roles")',        'button:has-text("See Open Roles")',
        'a:has-text("Explore Careers")',       'button:has-text("Explore Careers")',
        'a:has-text("Search Jobs")',           'button:has-text("Search Jobs")',
        'a:has-text("View Jobs")',             'button:has-text("View Jobs")',
        'a:has-text("Open Positions")',        'button:has-text("Open Positions")',
        'a:has-text("Current Openings")',      'button:has-text("Current Openings")',
        'a:has-text("Join Us")',               'button:has-text("Join Us")',
        'a:has-text("Careers")',
        '[class*="careers-link"]', '[class*="jobs-link"]',
    ]
    for sel in DISCOVERY_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.count() == 0 or not btn.is_visible(timeout=1500):
                continue
            print(f"    → Discovery click: {sel[:50]}")
            tabs_before = len(ctx.pages)
            btn.click(force=True)
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                page.wait_for_timeout(3000)
            # new tab opened?
            if len(ctx.pages) > tabs_before:
                page = ctx.pages[-1]
                page.bring_to_front()
                page.wait_for_timeout(2000)
            # now try to find the specific job title
            if target_title:
                try:
                    link = page.locator(f'a:has-text("{target_title}")').first
                    if link.count() > 0 and link.is_visible(timeout=2000):
                        print(f"    → Clicking: '{target_title}'")
                        link.click(force=True)
                        try:
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            page.wait_for_timeout(2500)
                        if len(ctx.pages) > tabs_before + 1:
                            page = ctx.pages[-1]
                            page.bring_to_front()
                except Exception:
                    pass
            if input_count(page) >= 3:
                return page, True
            break
        except Exception:
            continue

    # ── Step 3: look for any iframe that may contain the form ─────────────────
    frame_page, n = find_frame_with_form(page)
    if n >= 3:
        return page, True

    # ── Step 4: LLM navigator — ask Ollama what to click ─────────────────────
    if llm_popup_navigator(page, max_steps=3):
        return page, True

    return page, False


def search_and_click_specific_job(page, ctx, target_title):
    """
    On a job listings index page, find and click the link matching target_title.
    Handles partial matches and new-tab navigation.
    """
    tabs_before = len(ctx.pages)
    # try exact then partial title
    for attempt in [target_title,
                    " ".join(target_title.split()[:4]),
                    target_title.split("-")[0].strip()]:
        try:
            link = page.locator(f'a:has-text("{attempt}")').first
            if link.count() > 0 and link.is_visible(timeout=2000):
                print(f"    → Clicking listing: '{attempt}'")
                link.click(force=True)
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    page.wait_for_timeout(2500)
                if len(ctx.pages) > tabs_before:
                    page = ctx.pages[-1]
                    page.bring_to_front()
                    page.wait_for_timeout(2000)
                return page, True
        except Exception:
            continue
    return page, False


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

HANDLERS = {
    "greenhouse":     GreenhouseHandler,
    "lever":          LeverHandler,
    "workable":       WorkableHandler,
    "smartrecruiters":SmartRecruitersHandler,
    "ashby":          AshbyHandler,
    "workday":        ManualHandler,
    "oracle":         ManualHandler,
    "taleo":          ManualHandler,
    "google":         ManualHandler,
    "apple":          ManualHandler,
    "amazon":         ManualHandler,
}

def get_handler(ats, *args, **kwargs):
    cls = HANDLERS.get(ats, GenericHandler)
    return cls(*args, **kwargs)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main(db_path=r"C:\JobAgentData\job_agent.db"):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pip install playwright && playwright install chromium")
        return {}

    # ── DB setup with WAL mode (prevents corruption) ─────────────────────────
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    c = conn.cursor()

    c.execute("""
        SELECT jobpostingid, company, title, url, status, jd_text
        FROM seen_jobs
        WHERE status IN ('GENERATED_YES','GENERATED_MAYBE','MANUAL_APPLY')
        ORDER BY
          CASE status
            WHEN 'GENERATED_YES'   THEN 0
            WHEN 'GENERATED_MAYBE' THEN 1
            ELSE 2
          END,
          date_found DESC
    """)
    jobs  = c.fetchall()
    total = len(jobs)

    if not jobs:
        print("No jobs in queue.")
        conn.close()
        return {}

    auto = sum(1 for j in jobs if j[4] != "MANUAL_APPLY")
    man  = sum(1 for j in jobs if j[4] == "MANUAL_APPLY")
    print(f"\n{'='*55}")
    print(f"  Stage 3 — {total} jobs  ({auto} auto, {man} manual)")
    print(f"  Handlers: Greenhouse, Lever, Workable, SmartRecruiters, Ashby + Generic")
    print(f"{'='*55}\n")

    results = {"applied": 0, "skipped": 0, "no_pdf": 0, "expired": 0}
    os.makedirs(BROWSER_PROFILE, exist_ok=True)

    with sync_playwright() as pw:
        # randomized viewport — each session looks slightly different
        vw = random.randint(1260, 1300)
        vh = random.randint(880, 920)

        ctx = pw.chromium.launch_persistent_context(
            BROWSER_PROFILE,
            headless=False,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-session-crashed-bubble",
                "--hide-crash-restore-bubble",
            ],
            viewport={"width": vw, "height": vh},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/Chicago",
        )
        # stealth: mask webdriver flag that ATS bot-detection looks for
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = {runtime: {}};
        """)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # dismiss "Restore pages?" crash recovery popup if present
        try:
            page.evaluate("""() => {
                const btns = [...document.querySelectorAll('button')];
                const x = btns.find(b => /close|dismiss|no thanks|don.t restore/i.test(b.innerText));
                if (x) x.click();
            }""")
        except Exception:
            pass

        for idx, (job_id, company, title, url, status, jd_text) in enumerate(jobs, 1):
            # clear Ollama cache per job
            _CACHE.clear()

            ats     = detect_ats(url)
            job_dir = get_output_dir(company, title)
            res_pdf = find_file(job_dir, "resume", "pdf")
            cl_pdf  = find_file(job_dir, "cover_letter", "pdf")
            is_man  = (status == "MANUAL_APPLY") and (ats != "linkedin")

            print(f"\n{'─'*55}")
            print(f"[{idx}/{total}] [{status.replace('GENERATED_','')}]  {company}")
            print(f"Role:   {title}")
            print(f"ATS:    {ats.upper()}")
            print(f"Folder: {job_dir}")
            print(f"Resume: {res_pdf or '❌ NOT FOUND'}")
            if cl_pdf:
                print(f"CL:     {cl_pdf}")

            # open folder in Explorer
            open_folder(job_dir)

            # no PDF
            if not res_pdf:
                tex = find_file(job_dir, "resume", "tex")
                print(f"  → {'Compile .tex at overleaf.com' if tex else 'Run stage2 first'}")
                # safe DB update
                with conn:
                    c.execute(
                        "UPDATE seen_jobs SET status='MANUAL_NO_PDF' WHERE jobpostingid=?",
                        (job_id,)
                    )
                results["no_pdf"] += 1
                continue

            # navigate — with transaction safety
            try:
                # get a fresh page
                try:
                    page.title()
                except Exception:
                    page = ctx.new_page()

                print(f"\n  Opening: {url[:85]}")
                page.goto(url, timeout=40000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

            except Exception as e:
                print(f"  Nav error: {e}")
                try:
                    page = ctx.new_page()
                    page.goto(url, timeout=40000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                except Exception:
                    print(f"  Could not open — marking manual")
                    with conn:
                        c.execute(
                            "UPDATE seen_jobs SET status='MANUAL_APPLY' WHERE jobpostingid=?",
                            (job_id,)
                        )
                    results["skipped"] += 1
                    continue

            # check for expired page
            try:
                body_txt = page.locator("body").inner_text().lower()
                if any(p in body_txt for p in [
                    "server error", "error processing your request",
                    "page not found", "job has been filled",
                    "no longer accepting", "posting has expired",
                    "job is no longer available", "this job is closed",
                ]):
                    print("  → Expired/error page — skipping")
                    with conn:
                        c.execute(
                            "UPDATE seen_jobs SET status='EXPIRED' WHERE jobpostingid=?",
                            (job_id,)
                        )
                    results["expired"] += 1
                    continue
            except Exception:
                pass

            # ── LinkedIn Gateway Interception ─────────────────────────────────
            # LinkedIn "Apply" opens a new tab to the real company ATS.
            # Three strategies in order:
            # A) Extract direct URL from button href/data-url attribute
            # B) Trap new tab with ctx.expect_page() context manager
            # C) Give user 5 seconds to click manually (login wall)
            if ats == "linkedin" and not is_man:
                print("  LinkedIn gateway — extracting external ATS target...")
                try:
                    li_btn = page.locator(
                        '.jobs-apply-button, '
                        'button:has-text("Apply on company website"), '
                        'a:has-text("Apply on company website"), '
                        'button:has-text("Apply"), '
                        'a:has-text("Apply")'
                    ).first

                    if li_btn.count() > 0 and li_btn.is_visible(timeout=4000):

                        # Strategy A: extract direct URL from DOM attributes
                        external_url = None
                        try:
                            external_url = (
                                li_btn.get_attribute("href") or
                                li_btn.get_attribute("data-url") or
                                li_btn.get_attribute("data-apply-url")
                            )
                        except Exception:
                            pass

                        if external_url and "http" in external_url and "linkedin.com" not in external_url:
                            print(f"    → Strategy A: direct URL from DOM → {external_url[:60]}")
                            page.goto(external_url, wait_until="domcontentloaded", timeout=15000)
                            page.wait_for_timeout(2000)

                        else:
                            # Strategy B: trap new tab with expect_page()
                            print("    → Strategy B: trapping new tab...")
                            try:
                                with ctx.expect_page(timeout=6000) as new_page_info:
                                    li_btn.click(force=True)
                                new_page = new_page_info.value
                                new_page.bring_to_front()
                                try:
                                    new_page.wait_for_load_state("domcontentloaded", timeout=8000)
                                except Exception:
                                    new_page.wait_for_timeout(3000)
                                page = new_page

                            except Exception:
                                # Strategy C: LinkedIn login wall blocked it — 5s manual window
                                print("    → Strategy C: login wall detected.")
                                print("    *** Click Apply on LinkedIn manually — 5 seconds ***")
                                page.wait_for_timeout(5000)

                    # sync to active tab
                    page = ctx.pages[-1] if ctx.pages else page
                    page.bring_to_front()
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=6000)
                    except Exception:
                        pass

                    new_ats = detect_ats(page.url)
                    print(f"  → URL: {page.url[:70]}")
                    print(f"  → ATS: {new_ats.upper()}")
                    ats = new_ats

                    # if still on linkedin after all strategies → manual
                    if "linkedin.com" in page.url.lower():
                        print("  → Still on LinkedIn — treating as manual")
                        is_man = True

                except Exception as e:
                    print(f"  LinkedIn gateway error: {e}")


            # ── Discovery Router ──────────────────────────────────────────────
            # If URL is a company landing/careers page (not a direct ATS form),
            # navigate through it to find the actual application form.
            # Note: linkedin is allowed here — after gateway interception above,
            # ats has already been re-detected as the real company ATS.
            if ats not in ("oracle", "taleo", "google", "apple", "amazon") and not is_man:
                try:
                    n_inputs = page.locator('input:not([type="hidden"])').count()
                    if n_inputs < 3:
                        page, found = resolve_careers_landing_page(
                            page, ctx, target_title=title
                        )
                        if found:
                            # re-detect ATS after navigation (may have landed on Greenhouse etc.)
                            new_ats = detect_ats(page.url)
                            if new_ats != "unknown" and new_ats != ats:
                                print(f"  → ATS re-detected: {new_ats.upper()}")
                                ats = new_ats
                        else:
                            print("  → Could not resolve to application form")
                except Exception:
                    pass

            # build handler (with updated page + possibly re-detected ats)
            handler = get_handler(
                ats, page, ctx, url, res_pdf, cl_pdf,
                job_dir, company, title, jd_text
            )

            # MANUAL ONLY portals
            if is_man or ats in ("oracle", "taleo", "google", "apple", "amazon"):
                handler.apply()
                choice = input("\n  [Enter = applied,  s = skip] > ").strip().lower()
                if choice == "s":
                    results["skipped"] += 1
                else:
                    with conn:
                        c.execute(
                            "UPDATE seen_jobs SET status='APPLIED' WHERE jobpostingid=?",
                            (job_id,)
                        )
                    results["applied"] += 1
                continue

            # AUTO FILL
            fill_ok = False
            try:
                fill_ok = handler.apply()
            except Exception as e:
                print(f"  Handler error: {e}")

            if not fill_ok and not handler.check_confirmation():
                # form not found — ask user
                print(f"\n  ┌─────────────────────────────────────────────┐")
                print(f"  │  Form not found / fill failed.               │")
                print(f"  │  Navigate to form in browser → press Enter   │")
                print(f"  │  Type 's' to skip                            │")
                print(f"  └─────────────────────────────────────────────┘")
                inp = input("  [Enter = form ready,  s = skip] > ").strip().lower()
                if inp == "s":
                    with conn:
                        c.execute(
                            "UPDATE seen_jobs SET status='MANUAL_APPLY' WHERE jobpostingid=?",
                            (job_id,)
                        )
                    results["skipped"] += 1
                    continue
                # try generic fill after user navigates
                try:
                    handler2 = GenericHandler(
                        page, ctx, url, res_pdf, cl_pdf,
                        job_dir, company, title, jd_text
                    )
                    handler2._fill_page(handler2.frame)
                except Exception:
                    pass

            # bring browser to front
            try:
                page = ctx.pages[-1] if ctx.pages else page
                page.bring_to_front()
            except Exception:
                pass

            print(f"\n  ✅ Filled — review in browser and click Submit")
            print(f"  Check: name, email, phone, dropdowns, open answers")
            print()
            choice = input("  [Enter = I submitted,  s = skip] > ").strip().lower()

            if choice == "s":
                print(f"  → Skipped")
                with conn:
                    c.execute(
                        "UPDATE seen_jobs SET status='MANUAL_APPLY' WHERE jobpostingid=?",
                        (job_id,)
                    )
                results["skipped"] += 1
                continue

            page.wait_for_timeout(2000)
            page = ctx.pages[-1] if ctx.pages else page
            if handler.check_confirmation():
                print(f"  → ✅ Confirmation detected!")
            else:
                print(f"  → Marked APPLIED")

            with conn:
                c.execute(
                    "UPDATE seen_jobs SET status='APPLIED' WHERE jobpostingid=?",
                    (job_id,)
                )
            results["applied"] += 1
            page.wait_for_timeout(2000)

        print(f"\n{'='*55}")
        print(f"  All {total} jobs done.")
        input("Press Enter to close browser > ")
        ctx.close()

    print(f"\n=== Results ===")
    print(f"  Applied:  {results['applied']}")
    print(f"  Skipped:  {results['skipped']}")
    print(f"  No PDF:   {results['no_pdf']}")
    print(f"  Expired:  {results['expired']}")
    conn.close()
    return results


if __name__ == "__main__":
    main()