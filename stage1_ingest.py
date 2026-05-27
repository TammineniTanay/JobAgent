"""
stage1_ingest.py
Reads jobs from Excel + GitHub repos, scrapes missing JDs,
applies all filters, deduplicates, queues survivors in SQLite.
"""

import sqlite3
import pandas as pd
import requests
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

MAX_YEARS   = 3
MAX_JOB_AGE = 21    # days (0 = disable)

GITHUB_REPOS = [
    # Active 2026 new grad — standard markdown table format, works with our parser
    {
        "repo":   "vanshb03/New-Grad-2026",
        "branch": "dev",
        "file":   "README.md",
        "format": "markdown"
    },
    # Reliable markdown table, 46 roles confirmed working
    {
        "repo":   "ReaVNaiL/New-Grad-2024",
        "branch": "main",
        "file":   "README.md",
        "format": "markdown"
    },
    # Summer 2026 internships
    {
        "repo":   "pittcsc/Summer2025-Internships",
        "branch": "dev",
        "file":   "README.md",
        "format": "markdown"
    },
]

# ── roles you WANT ────────────────────────────────────────────────────────────
TARGET_KEYWORDS = [
    # AI / ML core
    "ai engineer", "ml engineer", "ai developer", "ml developer",
    "machine learning engineer", "deep learning engineer",
    "machine learning", "deep learning", "artificial intelligence",
    # LLM / GenAI
    "llm", "genai", "gen ai", "generative ai", "large language model",
    "ai agent", "agentic",
    # NLP / RAG / Search
    "nlp", "natural language processing", "natural language",
    "rag", "retrieval augmented", "retrieval engineer",
    "langchain", "llamaindex", "vector search", "embedding",
    "conversational ai",
    # Data Science
    "data scientist", "data science",
    "applied scientist", "research scientist", "applied researcher",
    # Data Engineering
    "data engineer", "data engineering", "etl engineer", "etl developer",
    "analytics engineer", "data analytics engineer",
    "data quality engineer", "data platform engineer",
    "pipeline engineer",
    # MLOps / Platform
    "mlops", "ml platform", "ai platform", "model deployment",
    "ml infrastructure", "ai infrastructure",
    # Computer Vision
    "computer vision", "cv engineer", "image recognition",
    "vision engineer", "perception engineer",
    # AI-specific internships
    "ai intern", "ml intern", "data science intern",
    "machine learning intern", "research intern",
]

# regex patterns for titles — broader SWE + AI catch
SW_AI_RE = [
    r"software\s+engineer.{0,40}(ai|ml|machine\s*learning|generative|llm|nlp|data\s+infra)",
    r"(ai|ml|machine\s*learning|generative|llm|nlp).{0,40}software\s+engineer",
    r"engineer.{0,30}(artificial\s+intelligence|deep\s+learning|neural\s+net)",
    r"(artificial\s+intelligence|deep\s+learning|neural\s+net).{0,30}engineer",
    r"software\s+engineer.{0,20}(intern|new\s*grad|entry\s*level)",
]

# ── JD keyword pre-screen — job must mention at least ONE of these in JD ─────
# prevents generic SWE roles from slipping through on title alone
JD_RELEVANCE_KEYWORDS = [
    "machine learning", "deep learning", "neural network",
    "llm", "large language model", "generative ai", "genai",
    "langchain", "langraph", "rag", "retrieval", "vector",
    "natural language", "nlp", "computer vision", "yolo",
    "pytorch", "tensorflow", "scikit", "xgboost",
    "data science", "data scientist", "data engineer",
    "etl", "databricks", "pyspark", "spark",
    "mlops", "model deployment", "model serving",
    "ai engineer", "ml engineer", "ai developer",
    "openai", "anthropic", "hugging face", "transformers",
    "embedding", "fine.tun", "qlora", "lora",
    "agentic", "ai agent", "copilot", "chatbot",
    "fastapi", "data pipeline", "feature engineering",
]

# ── senior title patterns — word-boundary safe ───────────────────────────────
SENIOR_TITLE_PATTERNS = [
    r"\bsenior\b", r"\bsr\b\.?(?=\s)", r"\bstaff\b",
    r"\bprincipal\b(?!\s+component)",
    r"\bdirector\b",
    r"\bhead\s+of\b",
    r"\bvice\s+president\b", r"\bvp\b(?:\s|$)",
    r"\bchief\b",
    r"\bdistinguished\b",
    r"\bfellow\b(?:\s|$)",
    r"\blead\s+(engineer|developer|scientist|architect|analyst|researcher)\b",
    r"\b(engineering|product|program|project|account|people|technical)\s+manager\b",
    r"\bmanaging\s+(director|partner|consultant)\b",
    r"\b(engineering|technical|research)\s+director\b",
]

BLOCKED_DOMAINS = [
    "linkedin.com", "dice.com", "jobright", "indeed.com",
    "ziprecruiter", "glassdoor", "monster.com", "careerbuilder",
    "simplyhired", "talent.com", "jobs-search",
]

BLOCKED_COMPANIES = [
    "kforce", "jobs via dice", "robert half",
    "teksystems", "tek systems", "infosys bpm",
    "staffing solutions", "staffing inc", "staffing llc",
    "recruiting firm", "wipro bps", "cognizant staffing",
]

CLEARANCE_BLOCKS = [
    "security clearance", "top secret", "ts/sci", "secret clearance",
    "dod clearance", "active clearance", "clearance required",
    "clearance is required", "must possess a clearance",
    "must be us citizen", "us citizen only", "us citizenship required",
    "must hold citizenship", "us person required", "itar restriction",
    "us nationals only", "must be a citizen of the united states",
    "eligible to obtain a clearance", "obtain a security clearance",
    "must have an active", "public trust clearance",
]

PHD_BLOCKS = [
    "phd required", "ph.d. required", "doctorate required",
    "doctoral degree required", "phd is required",
    "must have a phd", "must hold a phd",
    "requires a phd", "requires ph.d",
    "advanced degree required",
    r"minimum qualification.*phd",
]

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────

def init_db(path="job_agent.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            jobpostingid  TEXT PRIMARY KEY,
            url           TEXT,
            url_norm      TEXT,
            company       TEXT,
            title         TEXT,
            date_found    TEXT,
            status        TEXT,
            jd_text       TEXT,
            source        TEXT DEFAULT 'excel',
            date_posted   TEXT
        )
    """)
    # auto-migrate older schemas
    existing = {row[1] for row in c.execute("PRAGMA table_info(seen_jobs)")}
    for col, defn in [
        ("url_norm",    "TEXT"),
        ("source",      "TEXT DEFAULT 'excel'"),
        ("date_posted", "TEXT"),
    ]:
        if col not in existing:
            try:
                c.execute(f"ALTER TABLE seen_jobs ADD COLUMN {col} {defn}")
            except Exception:
                pass
    # clean up any rows that have timestamps in status (migration artefact)
    c.execute("DELETE FROM seen_jobs WHERE status LIKE '2026-%' OR status LIKE '2025-%'")
    conn.commit()
    return conn

# ─────────────────────────────────────────────────────────────────────────────
# URL NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

KEEP_PARAMS = {
    "gh_jid", "jobid", "job_id", "req", "reqid", "id",
    "opportunityid", "currentjobid", "positionid",
}

def normalize_url(url):
    try:
        p      = urlparse(url.strip())
        params = parse_qs(p.query, keep_blank_values=False)
        kept   = {k: v[0] for k, v in params.items() if k.lower() in KEEP_PARAMS}
        query  = urlencode(sorted(kept.items()))
        return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", query, ""))
    except Exception:
        return url.strip().lower()

# ─────────────────────────────────────────────────────────────────────────────
# JD SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def scrape_jd_text(url, timeout=12):
    try:
        resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return ""
        html = resp.text
        for tag in ["script", "style", "nav", "header", "footer", "noscript"]:
            html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
                          flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&[a-z]+;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:5000]
    except Exception:
        return ""

def scrape_missing_jds(conn, batch_size=30):
    c = conn.cursor()
    c.execute("""
        SELECT jobpostingid, url FROM seen_jobs
        WHERE status='TO_PROCESS' AND (jd_text IS NULL OR jd_text='')
        LIMIT ?
    """, (batch_size,))
    rows = c.fetchall()
    if not rows:
        return
    print(f"\n  Scraping JDs for {len(rows)} GitHub jobs...")
    scraped = 0
    for job_id, url in rows:
        text = scrape_jd_text(url)
        if text and len(text) > 100:
            c.execute("UPDATE seen_jobs SET jd_text=? WHERE jobpostingid=?", (text, job_id))
            scraped += 1
    conn.commit()
    print(f"  Scraped {scraped}/{len(rows)} JDs successfully.")

# ─────────────────────────────────────────────────────────────────────────────
# GITHUB POLLER
# ─────────────────────────────────────────────────────────────────────────────

def poll_github(token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    all_jobs = []
    for cfg in GITHUB_REPOS:
        url = (f"https://raw.githubusercontent.com/"
               f"{cfg['repo']}/{cfg['branch']}/{cfg['file']}")
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"  [GitHub] {cfg['repo']} — HTTP {resp.status_code}")
                continue
            fmt  = cfg.get("format", "markdown")
            jobs = (_parse_listings_json(resp.text, cfg["repo"])
                    if fmt == "json"
                    else _parse_readme(resp.text, cfg["repo"]))
            print(f"  [GitHub] {cfg['repo']} — {len(jobs)} open roles")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  [GitHub] {cfg['repo']} — error: {e}")
    return all_jobs


def _parse_listings_json(content, repo_name):
    """Parse SimplifyJobs listings.json format."""
    jobs = []
    try:
        import json as _json
        data = _json.loads(content)
    except Exception:
        return jobs
    for item in data:
        if not item.get("active", True):
            continue
        url = item.get("url") or item.get("apply_url") or ""
        if not url:
            continue
        company = item.get("company_name") or item.get("company") or ""
        title   = item.get("title") or item.get("role") or ""
        if not company or not title:
            continue
        job_id = (f"GH-{re.sub(r'[^a-z0-9]','',repo_name.lower())}"
                  f"-{abs(hash(url)) % 9999999}")
        jobs.append({
            "id":      job_id,
            "title":   title,
            "company": company,
            "url":     url,
            "jd":      "",
            "source":  "github",
            "date":    "",
        })
    return jobs


def _parse_readme(content, repo_name):
    jobs       = []
    apply_re   = re.compile(
        r"\[(?:Apply|Application|🔗|Link|Here|apply)[^\]]*\]\(([^)]+)\)",
        re.IGNORECASE
    )
    raw_url_re = re.compile(r"(https?://[^\s\)\"\|']{10,})")
    locked_re  = re.compile(r"🔒")
    row_re     = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]*)\|", re.MULTILINE)

    for m in row_re.finditer(content):
        col1 = m.group(1).strip()
        col2 = m.group(2).strip()
        row  = m.group(0)

        if any(x in col1.lower() for x in ["company", "---", "role", "name"]):
            continue
        if "---" in col1:
            continue
        if locked_re.search(row):
            continue

        url_m = apply_re.search(row) or raw_url_re.search(row)
        if not url_m:
            continue

        apply_url = url_m.group(1).strip()
        company   = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", col1).strip("* \t")
        role      = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", col2).strip("* \t")

        if not company or not role or len(company) < 2:
            continue
        if company.lower() in ("company", "name", "---"):
            continue

        job_id = (f"GH-{re.sub(r'[^a-z0-9]','',repo_name.lower())}"
                  f"-{abs(hash(apply_url)) % 9999999}")
        jobs.append({
            "id": job_id, "title": role, "company": company,
            "url": apply_url, "jd": "", "source": "github", "date": "",
        })
    return jobs

# ─────────────────────────────────────────────────────────────────────────────
# FILTERS
# ─────────────────────────────────────────────────────────────────────────────

def is_senior_title(title):
    t = title.lower().strip()
    if re.search(r"\b(iii|iv|v)\b", t):
        return True
    for pattern in SENIOR_TITLE_PATTERNS:
        if re.search(pattern, t):
            return True
    return False


def is_target_role(title):
    t = title.lower().strip()
    if is_senior_title(title):
        return False
    if any(kw in t for kw in TARGET_KEYWORDS):
        return True
    for pat in SW_AI_RE:
        if re.search(pat, t):
            return True
    return False


def jd_is_relevant(jd_text):
    """
    Secondary screen: JD must mention at least one AI/ML/data keyword.
    Prevents generic SWE roles from passing on title alone.
    Only applied when JD text is available (>200 chars).
    """
    if not jd_text or len(jd_text.strip()) < 200:
        return True   # no JD available — give benefit of doubt
    j = jd_text.lower()
    return any(re.search(kw, j) for kw in JD_RELEVANCE_KEYWORDS)


def check_experience(jd_text):
    if not jd_text or len(jd_text.strip()) < 10:
        return True
    j    = jd_text.lower()
    mins = []

    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                   "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

    for pat in [
        r"minimum\s+(?:of\s+)?(\d+)\+?\s*years?",
        r"at\s+least\s+(\d+)\s*years?",
        r"requires?\s+(\d+)\+?\s*years?",
        r"(\d+)\+\s*years?\s+(?:of\s+)?(?:experience|exp\b)",
        r"(\d+)\s*years?\s+(?:of\s+)?(?:relevant|professional|industry|work)\s+exp",
    ]:
        for m in re.finditer(pat, j):
            try:
                mins.append(int(m.group(1)))
            except Exception:
                pass

    for m in re.finditer(r"(\d+)\s*[-–]\s*(\d+)\s*years?", j):
        try:
            mins.append(int(m.group(1)))
        except Exception:
            pass

    for word, num in word_to_num.items():
        for pat in [
            rf"minimum\s+(?:of\s+)?{word}\s+years?",
            rf"at\s+least\s+{word}\s+years?",
            rf"{word}\s+years?\s+(?:of\s+)?(?:experience|exp\b)",
        ]:
            if re.search(pat, j):
                mins.append(num)

    if not mins:
        return True
    return min(mins) <= MAX_YEARS


def check_phd(jd_text):
    if not jd_text:
        return True
    j = jd_text.lower()
    for pat in PHD_BLOCKS:
        if re.search(pat, j):
            return False
    return True


def check_clearance(jd_text):
    if not jd_text:
        return True
    return not any(kw in jd_text.lower() for kw in CLEARANCE_BLOCKS)


def check_age(date_str):
    if MAX_JOB_AGE == 0 or not date_str:
        return True
    try:
        for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y"]:
            try:
                posted = datetime.strptime(str(date_str).strip(), fmt)
                return (datetime.now() - posted).days <= MAX_JOB_AGE
            except ValueError:
                continue
    except Exception:
        pass
    return True


def is_blocked_url(url):
    if not isinstance(url, str) or not url.strip():
        return True
    return any(d in url.lower() for d in BLOCKED_DOMAINS)


def is_blocked_company(company):
    if not isinstance(company, str):
        return False
    return any(b in company.lower() for b in BLOCKED_COMPANIES)

# ─────────────────────────────────────────────────────────────────────────────
# EXCEL LOADER
# ─────────────────────────────────────────────────────────────────────────────

def load_excel(path):
    df = pd.read_excel(path)
    df = df.rename(columns={
        "Jobpostingid":   "id",
        "Title":          "title",
        "Company name":   "company",
        "JobPostedDate":  "date",
        "Joburl":         "url",
        "JobDescription": "jd",
    })
    df["source"] = "excel"
    df = df.dropna(subset=["title", "url"])
    return df

# ─────────────────────────────────────────────────────────────────────────────
# PROCESS
# ─────────────────────────────────────────────────────────────────────────────

def process_jobs(jobs_list, conn):
    c = conn.cursor()
    actionable = []
    stats = {
        "total": 0, "blocked_domain": 0, "blocked_company": 0,
        "wrong_role": 0, "too_old": 0, "not_relevant_jd": 0,
        "overqualified": 0, "phd_required": 0, "clearance": 0,
        "duplicate": 0, "queued": 0,
    }

    for job in jobs_list:
        stats["total"] += 1

        url      = str(job.get("url", "")).strip()
        title    = str(job.get("title", "")).strip()
        company  = str(job.get("company", "")).strip()
        jd       = str(job.get("jd", "")) if job.get("jd") else ""
        source   = job.get("source", "excel")
        job_id   = str(job.get("id", url))
        date_str = str(job.get("date", ""))
        url_norm = normalize_url(url)

        if is_blocked_url(url):
            stats["blocked_domain"] += 1
            continue
        if is_blocked_company(company):
            stats["blocked_company"] += 1
            continue
        if not is_target_role(title):
            stats["wrong_role"] += 1
            continue
        if not check_age(date_str):
            stats["too_old"] += 1
            continue
        if not jd_is_relevant(jd):
            stats["not_relevant_jd"] += 1
            continue
        if not check_experience(jd):
            stats["overqualified"] += 1
            continue
        if not check_phd(jd):
            stats["phd_required"] += 1
            continue
        if not check_clearance(jd):
            stats["clearance"] += 1
            continue

        c.execute(
            "SELECT jobpostingid FROM seen_jobs WHERE jobpostingid=? OR url_norm=?",
            (job_id, url_norm)
        )
        if c.fetchone():
            stats["duplicate"] += 1
            continue

        # named columns — works on any schema version
        c.execute("""
            INSERT INTO seen_jobs
                (jobpostingid, url, url_norm, company, title,
                 date_found, status, jd_text, source, date_posted)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            job_id, url, url_norm, company, title,
            datetime.now().isoformat(), "TO_PROCESS", jd, source, date_str
        ))

        stats["queued"] += 1
        actionable.append({
            "id": job_id, "title": title,
            "company": company, "url": url, "jd": jd,
        })

    conn.commit()
    return actionable, stats

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main(excel_path="daily_jobs.xlsx", github_token=None, db_path="job_agent.db"):
    conn     = init_db(db_path)
    all_jobs = []

    print("\n[Stage 1] Loading Excel...")
    try:
        df         = load_excel(excel_path)
        excel_jobs = df[["id","title","company","date","url","jd","source"]].to_dict("records")
        all_jobs.extend(excel_jobs)
        print(f"  Excel: {len(excel_jobs)} rows loaded")
    except FileNotFoundError:
        print(f"  '{excel_path}' not found — skipping Excel")
    except Exception as e:
        print(f"  Excel error: {e}")

    print("\n[Stage 1] Polling GitHub repos...")
    all_jobs.extend(poll_github(token=github_token))

    print(f"\n[Stage 1] Filtering {len(all_jobs)} total rows...")
    actionable, stats = process_jobs(all_jobs, conn)

    scrape_missing_jds(conn)

    print("\n=== Stage 1 Results ===")
    print(f"  Total rows:          {stats['total']}")
    print(f"  Blocked (URL):       {stats['blocked_domain']}")
    print(f"  Blocked (company):   {stats['blocked_company']}")
    print(f"  Wrong role/title:    {stats['wrong_role']}")
    print(f"  Too old (>{MAX_JOB_AGE}d):      {stats['too_old']}")
    print(f"  JD not AI/ML rel.:   {stats['not_relevant_jd']}")
    print(f"  Too senior/exp:      {stats['overqualified']}")
    print(f"  PhD required:        {stats['phd_required']}")
    print(f"  Clearance/citizen:   {stats['clearance']}")
    print(f"  Duplicates:          {stats['duplicate']}")
    print(f"  Queued for resume:   {stats['queued']}")
    print(f"\n  Actionable today: {len(actionable)}")
    print("  " + "-" * 42)
    for j in actionable:
        print(f"  [{j['company']}] {j['title']}")
        print(f"  {j['url']}")

    conn.close()
    return actionable


if __name__ == "__main__":
    main()