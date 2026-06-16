# JobAgent

Zero-cost automated job application pipeline built with Python, Playwright, SQLite, and Ollama.

## What It Does

JobAgent automates the repetitive parts of job hunting:

1. **Ingest** — reads job listings from Excel files into a SQLite database
2. **Generate** — uses Ollama (local LLM) to tailor resume content for each job
3. **Apply** — uses Playwright to auto-fill ATS forms on Greenhouse, Lever, Workable, SmartRecruiters, and Ashby
4. **Track** — maintains a live HTML dashboard showing application status

## Pipeline Stages

| File | Stage | What it does |
|---|---|---|
| `stage1_ingest.py` | Ingest | Reads Excel, deduplicates, stores jobs in SQLite |
| `stage2_generate.py` | Generate | Ollama scores job fit, generates tailored resume bullets |
| `stage3_apply.py` | Apply | Playwright auto-fills ATS forms per platform |
| `run_pipeline.py` | Orchestrator | Runs all stages end to end |
| `tracker.py` | Dashboard | Generates live HTML tracker |

## Tech Stack

- **Python** — core pipeline
- **Playwright** — browser automation for ATS form filling
- **SQLite** — local job tracking database
- **Ollama** — local LLM for resume generation (zero API cost)
- **Pandas** — Excel ingestion and data processing

## Setup

```bash
git clone https://github.com/TammineniTanay/JobAgent.git
cd JobAgent
pip install playwright pandas ollama
playwright install chromium
```

## Usage

```bash
# Run full pipeline
python run_pipeline.py

# Run individual stages
python stage1_ingest.py    # ingest jobs from Excel
python stage2_generate.py  # generate tailored content
python stage3_apply.py     # auto-fill ATS forms
python tracker.py          # update HTML dashboard
```

## Supported ATS Platforms

- Greenhouse
- Lever
- Workable
- SmartRecruiters
- Ashby

## Author

Tanay Tammineni — [GitHub](https://github.com/TammineniTanay) | [LinkedIn](https://linkedin.com/in/tanay-tammineni)