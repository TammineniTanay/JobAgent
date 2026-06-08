"""
stage2_generate.py
Generates resumes + cover letters for:
- TO_PROCESS jobs  → full pipeline, then auto-apply
- MANUAL_APPLY jobs (LinkedIn) → resume generated, status stays MANUAL_APPLY
Output organized in date-based subfolders: output/YYYY-MM-DD/company_role/
"""

import sqlite3
import requests
import json
import os
import re
import subprocess
import shutil
import time
from datetime import datetime

OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL_NAME   = "llama3.1:8b"
OUTPUT_DIR   = "output"
JOB_COOLDOWN = 10

TODAY_DIR = os.path.join(OUTPUT_DIR, datetime.now().strftime("%Y-%m-%d"))

# ─────────────────────────────────────────────────────────────────────────────
# CONFIRMED SKILL BANK
# ─────────────────────────────────────────────────────────────────────────────

CONFIRMED_SKILLS = {
    "Python","SQL","Java","R","PyTorch","TensorFlow","Scikit-learn","XGBoost",
    "LangChain","LlamaIndex","QLoRA","DeepSpeed","vLLM","DPO","LangGraph","RAGAS",
    "YOLOv8","OpenCV","MinHash LSH","AWS","Azure","GCP","Docker","Terraform","CI/CD",
    "GitHub Actions","Qdrant","Elasticsearch","Neo4j","PostgreSQL","MongoDB","Redis",
    "PySpark","Databricks","FastAPI","React","Prometheus","Grafana","REST APIs",
    "Git","Jupyter","Power BI","SQLite","FFmpeg","OpenAI Whisper",
}

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def fill_template(template, **kwargs):
    result = template
    for key, value in kwargs.items():
        result = result.replace("{{ " + key + " }}", str(value))
        result = result.replace("{{" + key + "}}", str(value))
    return result

def clean_text(text):
    banned = [
        "thrilled","delighted","honored","passionate about","spearheading",
        "leveraging","leverage","excited to apply","writing to apply",
        "i am excited","i am thrilled","i am honored","i am delighted",
    ]
    for w in banned:
        text = re.sub(re.escape(w), "", text, flags=re.IGNORECASE)
    return re.sub(r"  +", " ", text).strip()

def detect_ats_name(url):
    u = url.lower()
    if "greenhouse.io" in u or "gh_jid" in u:       return "Greenhouse"
    if "lever.co" in u or "jobs.lever" in u:         return "Lever"
    if "workday" in u or "myworkdayjobs" in u:       return "Workday"
    if "oraclecloud" in u or "fa.em" in u:           return "Oracle"
    if "taleo" in u:                                 return "Taleo"
    if "icims" in u:                                 return "iCIMS"
    if "smartrecruiters" in u:                       return "SmartRecruiters"
    if "paylocity" in u:                             return "Paylocity"
    if "adp" in u:                                   return "ADP"
    if "linkedin.com" in u:                          return "LinkedIn (manual)"
    if "google.com/about/careers" in u:              return "Google (manual)"
    if "apple.com" in u:                             return "Apple (manual)"
    if "workable" in u:                              return "Workable"
    if "rippling" in u:                              return "Rippling"
    if "ultipro" in u:                               return "UltiPro"
    return "Unknown"

def write_job_info(outdir, company, title, url, verdict, reason):
    with open(os.path.join(outdir, "job_info.txt"), "w", encoding="utf-8") as f:
        f.write(f"Company:  {company}\n")
        f.write(f"Role:     {title}\n")
        f.write(f"URL:      {url}\n")
        f.write(f"Verdict:  {verdict}\n")
        f.write(f"Reason:   {reason}\n")
        f.write(f"Date:     {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"ATS:      {detect_ats_name(url)}\n")

# ─────────────────────────────────────────────────────────────────────────────
# PROJECT KEYWORD OVERRIDE
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_OVERRIDES = [
    (r"computer vision|object detection|image recognit|yolo|opencv",  "P3"),
    (r"retrieval|vector search|rag|semantic search|embedding",         "P2"),
    (r"fine.tun|model training|qlora|deepspeed|llm training|lora",    "P1"),
    (r"etl|data pipeline|pyspark|databricks|data engineer",            "P5"),
    (r"audio|speech|websocket|real.time stream|ffmpeg|whisper",        "P4"),
    (r"langchain|langgraph|agentic|agent framework",                   "P2"),
    (r"generative ai|llm|large language|gpt|chatbot|copilot",         "P1"),
]

DEFAULT_PROJECT_ORDER = ["P1", "P2", "P3", "P4", "P5"]

def pick_projects(llm_projects, jd_text):
    jd_lower = (jd_text or "").lower()
    forced   = []
    for pattern, proj in PROJECT_OVERRIDES:
        if re.search(pattern, jd_lower) and proj not in forced:
            forced.append(proj)
        if len(forced) == 3:
            break
    merged = list(forced)
    for p in (llm_projects or []):
        if p in DEFAULT_PROJECT_ORDER and p not in merged:
            merged.append(p)
    for p in DEFAULT_PROJECT_ORDER:
        if p not in merged:
            merged.append(p)
    return merged[:3]

# ─────────────────────────────────────────────────────────────────────────────
# LLM PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

COMBINED_PROMPT = """You are a job application assistant for Tanay Tammineni. Output ONLY a valid JSON object. No explanation, no markdown, no text before { or after }.

{
  "verdict": "YES" or "MAYBE" or "NO",
  "reason": "one sentence under 12 words",
  "projects": ["P1", "P2", "P3"],
  "priority_skills": ["skill1", "skill2", "skill3", "skill4", "skill5", "skill6"],
  "summary_closing": "one sentence third person under 20 words: specific value Tanay brings to THIS company",
  "cl_para1": "2-3 sentences. Strong hook specific to this role/company. Never open with: I am writing, I am excited, I am thrilled, I would like.",
  "cl_para2": "2-3 sentences. Connect THIS company's specific product or mission to Tanay's actual work. Name something specific from the JD.",
  "cl_para4": "Exactly 2 sentences. Request interview. Second sentence verbatim: I am authorized to work in the U.S."
}

PROJECT SELECTION:
  P1 = Distributed LLM Fine-Tuning Pipeline  (ML/LLM/training/research)
  P2 = Production RAG System                  (RAG/search/NLP/GenAI/LangChain)
  P3 = Real-Time Vehicle Detection            (CV/vision or variety)
  P4 = LiveWire AI Extension                  (backend/systems/audio/API)
  P5 = Earthquake ML Pipeline                 (data engineering/PySpark/GCP/ETL)

SKILLS — only from this list:
  Python, SQL, Java, R, PyTorch, TensorFlow, Scikit-learn, XGBoost,
  LangChain, LlamaIndex, QLoRA, DeepSpeed, vLLM, DPO, LangGraph, RAGAS,
  YOLOv8, OpenCV, MinHash LSH, AWS, Azure, GCP, Docker, Terraform, CI/CD,
  GitHub Actions, Qdrant, Elasticsearch, Neo4j, PostgreSQL, MongoDB, Redis,
  PySpark, Databricks, FastAPI, React, Prometheus, Grafana, REST APIs,
  Git, Jupyter, Power BI, SQLite, FFmpeg, OpenAI Whisper

VERDICT RULES:
  NO    — requires security clearance, citizenship, or explicitly 4+ years experience
  YES   — strong AI/ML/LLM/data engineering match, 0-3 years level
  MAYBE — partial match or experience level unclear

WRITING RULES:
  - Never say: thrilled, delighted, leveraging, spearheading, passionate, excited, honored
  - Never mention OPT, STEM, H1B, visa, citizenship
  - cl_para1 and cl_para2 in first person
  - summary_closing in third person (Tanay, his)
  - cl_para4 second sentence: I am authorized to work in the U.S.

Output starts with { and ends with }. Nothing else."""

CL_RETRY_PROMPT = """Output ONLY a valid JSON object with these 3 keys. Start with { end with }.
{
  "cl_para1": "2-3 sentences opening a cover letter. Do not start with I am writing or I am excited.",
  "cl_para2": "2-3 sentences connecting the company work to LLM and RAG engineering experience.",
  "cl_para4": "Exactly 2 sentences. Last sentence must be: I am authorized to work in the U.S."
}"""

# ─────────────────────────────────────────────────────────────────────────────
# FIXED CONTENT BANKS
# ─────────────────────────────────────────────────────────────────────────────

SUMMARY_BODY = {
    "ml": (
        r"AI/ML Engineer with production experience building distributed LLM fine-tuning pipelines, "
        r"RAG retrieval systems, and model serving infrastructure on AWS and GCP. "
        r"Published researcher in UniLLMOps (Zenodo DOI: 10.5281/zenodo.19582347) with hands-on expertise "
        r"in PyTorch, QLoRA, DeepSpeed, LangChain, LangGraph, and RAGAS across end-to-end production systems."
    ),
    "backend": (
        r"AI Systems Engineer with production experience building real-time audio pipelines, "
        r"WebSocket servers, and LLM-powered backend services deployed at scale. "
        r"Published researcher in UniLLMOps (Zenodo DOI: 10.5281/zenodo.19582347) with expertise in "
        r"FastAPI, Python asyncio, Docker, LangChain, and cloud-native AI system integration."
    ),
    "data": (
        r"Data and AI Engineer with production experience building ETL pipelines, hybrid RAG systems, "
        r"and cloud-native ML infrastructure on AWS and Azure. "
        r"Published researcher in UniLLMOps (Zenodo DOI: 10.5281/zenodo.19582347) with expertise in "
        r"PySpark, Databricks, LangChain, PostgreSQL, and end-to-end data pipeline engineering."
    ),
    "default": (
        r"AI/ML Engineer with production experience building LLM fine-tuning pipelines, "
        r"RAG retrieval systems, and cloud-native model deployment infrastructure. "
        r"Published researcher in UniLLMOps (Zenodo DOI: 10.5281/zenodo.19582347) with expertise in "
        r"PyTorch, LangChain, FastAPI, Docker, and AWS across real-world AI production systems."
    ),
}

TOOLKIT_ROWS = {
    "ml": {
        "row1": r"PyTorch, TensorFlow, QLoRA, DeepSpeed, vLLM, LangChain, LangGraph, RAGAS",
        "row2": r"Python, SQL, AWS (S3, Bedrock, Lambda, DynamoDB), GCP, Azure, Docker, Databricks, PostgreSQL",
        "row3": r"FastAPI, REST APIs, Terraform, CI/CD, GitHub Actions, Git",
        "row4": r"Prometheus, Grafana, Jupyter, Power BI",
    },
    "backend": {
        "row1": r"PyTorch, TensorFlow, LangChain, LangGraph, OpenAI Whisper, FFmpeg, vLLM, RAGAS",
        "row2": r"Python, SQL, AWS (S3, Lambda, Bedrock), Azure, GCP, Docker, PostgreSQL, Redis, MongoDB",
        "row3": r"FastAPI, WebSocket, REST APIs, Terraform, CI/CD, GitHub Actions, Git",
        "row4": r"Prometheus, Grafana, Jupyter, Power BI",
    },
    "data": {
        "row1": r"PyTorch, TensorFlow, Scikit-learn, XGBoost, LangChain, LangGraph, RAGAS, QLoRA",
        "row2": r"Python, SQL, Java, PySpark, Databricks, AWS (S3, Lambda), Azure, PostgreSQL, MongoDB, Redis",
        "row3": r"FastAPI, REST APIs, Docker, CI/CD, GitHub Actions, Git",
        "row4": r"Power BI, Prometheus, Grafana, Jupyter",
    },
    "default": {
        "row1": r"PyTorch, TensorFlow, LangChain, LangGraph, QLoRA, DeepSpeed, vLLM, RAGAS",
        "row2": r"Python, SQL, AWS (S3, Bedrock, Lambda), Azure, GCP, Docker, PostgreSQL, MongoDB, Redis",
        "row3": r"FastAPI, REST APIs, Terraform, CI/CD, GitHub Actions, Git",
        "row4": r"Prometheus, Grafana, Jupyter, Power BI",
    },
}

def build_cl_para3(projects):
    p1 = "P1" in projects
    p2 = "P2" in projects
    p4 = "P4" in projects
    p5 = "P5" in projects
    if p1 and p2:
        return (
            r"My Distributed LLM Fine-Tuning Pipeline achieved 41.2\% per-GPU memory reduction "
            r"and 3.8x inference throughput on Llama 3 8B across 66 files and 11,000+ lines, "
            r"with methodology published in UniLLMOps (Zenodo DOI: 10.5281/zenodo.19582347). "
            r"My Production RAG System delivered 23.7\% retrieval faithfulness gain using hybrid "
            r"Qdrant, Elasticsearch, and Neo4j retrieval with CRAG via LangGraph."
        )
    elif p4:
        return (
            r"My LiveWire AI Extension processes real-time stereo audio over WebSocket with "
            r"16 normalized error codes and preflight diagnostics preventing failed sessions. "
            r"My Distributed LLM Fine-Tuning Pipeline achieved 41.2\% per-GPU memory reduction "
            r"and 3.8x inference throughput across 66 files and 11,000+ lines, published in "
            r"UniLLMOps (Zenodo DOI: 10.5281/zenodo.19582347)."
        )
    elif p2 and p5:
        return (
            r"My Production RAG System delivered 23.7\% retrieval faithfulness gain using hybrid "
            r"Qdrant, Elasticsearch, and Neo4j retrieval, published in UniLLMOps "
            r"(Zenodo DOI: 10.5281/zenodo.19582347). "
            r"My GCP pipeline used PySpark for distributed preprocessing and my LLM Fine-Tuning "
            r"Pipeline achieved 41.2\% per-GPU memory reduction across 11,000+ lines."
        )
    else:
        return (
            r"My Distributed LLM Fine-Tuning Pipeline achieved 41.2\% per-GPU memory reduction "
            r"and 3.8x inference throughput on Llama 3 8B across 66 files and 11,000+ lines, "
            r"published in UniLLMOps (Zenodo DOI: 10.5281/zenodo.19582347). "
            r"My Production RAG System delivered 23.7\% retrieval faithfulness gain using hybrid "
            r"Qdrant, Elasticsearch, and Neo4j retrieval with CRAG via LangGraph."
        )

VOICEBOTICS_BULLETS = {
    "whisper":    r"\item Built LiveWire Chrome extension using tabCapture API, FFmpeg stereo splitting, and OpenAI Whisper transcription to enable dual-channel audio capture across Zoom, Teams, and Google Meet via offscreen document architecture.",
    "fastapi":    r"\item Engineered FastAPI WebSocket server with Python asyncio and 60-second reconnect session management to generate evidence packs of WebM audio, MP3, timestamped transcript, and metadata.json per recorded call.",
    "watchdog":   r"\item Implemented STT latency watchdog tracking 5s warn and 8s degrade thresholds with a rolling average over 5 chunks, triggering automated recovery and forced reset after 5 consecutive degraded batches.",
    "errorcodes": r"\item Designed 16 normalized error codes with severity levels, platform-specific root cause mapping for Zoom, Teams, and Meet, next-step guidance codes, and JSONL instrumentation logging every pipeline event.",
    "preflight":  r"\item Built preflight diagnostic system running a 3-second audio test with 4 statuses and auto-retry logic, validating device state before every session to prevent silent capture failures.",
    "security":   r"\item Enforced security via X-API-Key header auth, CORS locked to a specific extension ID, all secrets from .env, and a mandatory P0 security review gate before every production deployment.",
}

GLOBALSHALA_BULLETS = [
    r"\item Built Java and SQL data management systems alongside Azure Databricks ETL pipelines, supporting operational data workflows across multiple cloud-native production environments.",
    r"\item Developed Power BI dashboards and Azure cloud integrations that maintained 99.9\% uptime across production deployments, supporting business intelligence and executive reporting operations.",
    r"\item Contributed to backend services through API integration work, SQL query optimization, and data pipeline maintenance tasks spanning a six-month software engineering internship.",
]

PROJECT_DATA = {
    "P1": {
        "title": "Distributed LLM Fine-Tuning Pipeline",
        "url":   "https://github.com/TammineniTanay/distributed-finetune-pipeline",
        "stack": "Python, PyTorch, QLoRA, DeepSpeed, vLLM, Terraform, Docker",
        "bullets": [
            r"\item Built QLoRA and DeepSpeed ZeRO-3 fine-tuning pipeline on Llama 3 8B across 66 files and 11,000+ lines, achieving 41.2\% per-GPU memory reduction and 3.8x inference throughput improvement.",
            r"\item Implemented MinHash LSH deduplication and LLM-as-judge quality scoring for the training data pipeline, ensuring corpus integrity and eliminating near-duplicate contamination before fine-tuning.",
            r"\item Deployed vLLM and AWQ serving with Prometheus and Grafana monitoring on AWS spot instances; published methodology in UniLLMOps paper (Zenodo DOI: 10.5281/zenodo.19582347).",
        ],
    },
    "P2": {
        "title": "Production RAG System",
        "url":   "https://github.com/TammineniTanay/hybrid-rag-system",
        "stack": "Python, LangChain, LangGraph, Qdrant, Elasticsearch, Neo4j, FastAPI, RAGAS",
        "bullets": [
            r"\item Built hybrid retrieval combining Qdrant dense search, Elasticsearch BM25, and Neo4j graph traversal with Reciprocal Rank Fusion, achieving 23.7\% retrieval faithfulness gain over single-index baseline.",
            r"\item Implemented CRAG via LangGraph state machine with query rewriting and web search fallback, reducing hallucination on out-of-corpus queries across a 783-chunk arXiv ML paper corpus.",
            r"\item Developed RLHF feedback loop with reward model reranking and a RAGAS evaluation dashboard in FastAPI and React, enabling continuous quality monitoring across 50-query benchmarks.",
        ],
    },
    "P3": {
        "title": "Real-Time Vehicle Detection",
        "url":   "https://github.com/TammineniTanay/realtime-Vechile-Detection-using-AI",
        "stack": "Python, YOLOv8, OpenCV, PyTorch, TensorFlow",
        "bullets": [
            r"\item Built real-time vehicle detection and classification system using YOLOv8 and OpenCV, achieving 88\% accuracy across 5,000+ frames processed in live traffic conditions.",
            r"\item Optimized inference pipeline by 25\% through model quantization and frame-skipping logic, enabling deployment on resource-constrained edge hardware without accuracy degradation.",
            r"\item Published in CVR Journal Vol.24 June 2023 and awarded 3rd Prize at Project Expo 2K23 for contribution to intelligent transportation systems research.",
        ],
    },
    "P4": {
        "title": "LiveWire AI Extension",
        "url":   "https://github.com/TammineniTanay/Live-Wire-AI",
        "stack": "Python, FastAPI, WebSocket, FFmpeg, OpenAI Whisper",
        "bullets": [
            r"\item Built Chrome MV3 extension with offscreen document architecture capturing stereo audio over WebSocket to a FastAPI server, with STT retry exponential backoff and hot-swap device detection.",
            r"\item Implemented 16 normalized error codes with JSONL instrumentation logging every session event, enabling platform-specific root cause mapping across Zoom, Teams, and Meet integrations.",
            r"\item Engineered platform fingerprinting and preflight diagnostics that validate audio device state before session start, preventing silent capture failures across all conferencing platforms.",
        ],
    },
    "P5": {
        "title": "Earthquake ML Pipeline",
        "url":   "https://github.com/TammineniTanay/Prredicting-the-Effects-of-Earthquakes-Using-Cloud-Based-ML",
        "stack": "Python, GCP, Scikit-learn, PySpark, Jupyter",
        "bullets": [
            r"\item Built a cloud-based ML pipeline on GCP using PySpark for distributed preprocessing of seismic event data, enabling scalable earthquake impact prediction across large geological datasets.",
            r"\item Trained and evaluated ensemble classifiers using Scikit-learn with stratified cross-validation and feature importance analysis to identify key geological and seismic risk indicators.",
            r"\item Deployed the prediction service on GCP with an automated retraining schedule and a Jupyter-based reporting dashboard for stakeholder visualization of model outputs.",
        ],
    },
}

ROLE_VB_MAP = {
    "ml":      ["watchdog", "fastapi", "errorcodes", "preflight"],
    "backend": ["fastapi", "whisper", "watchdog", "security"],
    "data":    ["fastapi", "errorcodes", "preflight", "security"],
    "default": ["whisper", "fastapi", "watchdog", "errorcodes"],
}

# ─────────────────────────────────────────────────────────────────────────────
# LATEX TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

RESUME_TEMPLATE = r"""\documentclass[letterpaper,10pt]{article}
\usepackage[T1]{fontenc}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{enumitem}
\usepackage[hidelinks, colorlinks=false, pdfborder={0 0 0}]{hyperref}
\usepackage{fancyhdr}
\usepackage{geometry}
\geometry{top=0.35in, bottom=0.35in, left=0.55in, right=0.55in}
\pagestyle{fancy}\fancyhf{}\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
\setlength{\parindent}{0pt}\setlength{\parskip}{0pt}
\setlength{\topsep}{0pt}\setlength{\partopsep}{0pt}
\setlength{\itemsep}{0pt}\setlength{\parsep}{0pt}
\setlength{\tabcolsep}{0in}
\titleformat{\section}{\bfseries\normalsize\normalfont\bfseries}{}{0em}{}[\vspace{-8pt}\rule{\linewidth}{0.6pt}]
\titlespacing*{\section}{0pt}{2pt}{0pt}
\newcommand{\expheading}[4]{\noindent\textbf{#1}\hfill\small #2\\[-3pt]\textit{\small #3}\hfill\textit{\small #4}\\[-8pt]}
\newcommand{\projheading}[3]{\noindent\textbf{\href{#2}{#1}}\hfill\textit{\small #3}\\[-8pt]}
\newenvironment{cvbullets}{\begin{itemize}[leftmargin=0.18in,label=\textbullet,topsep=-4pt,itemsep=-1pt,parsep=0pt,partopsep=0pt]\small}{\end{itemize}\vspace{1pt}}
\begin{document}
\begin{center}
{\LARGE\bfseries \href{https://tanaytammineni.vercel.app/}{TANAY TAMMINENI}}\\[2pt]
\small
tanaytammineni22@gmail.com\ \textbar\ 816-277-9463\ \textbar\ USA\ \textbar\
\href{https://www.linkedin.com/in/tanay-tammineni/}{LinkedIn}\ \textbar\
\href{https://github.com/TammineniTanay}{GitHub}\ \textbar\
\href{https://tanaytammineni.vercel.app/}{Portfolio}
\end{center}
\section{Professional Summary}
\noindent\small {{ summary_paragraph }}
\section{Technical Toolkit}
\noindent\small
\textbf{AI/ML:} {{ skills_row1 }}\\
\textbf{Data \& Cloud:} {{ skills_row2 }}\\
\textbf{Backend \& Infra:} {{ skills_row3 }}\\
\textbf{Tools \& Monitoring:} {{ skills_row4 }}
\section{Professional Experience}
\expheading{VoiceBotics AI}{Remote}{AI Systems Developer Intern}{Apr 2025 --- Present}
\begin{cvbullets}
{{ vb_bullets }}
\end{cvbullets}
\vspace{2pt}
\expheading{Globalshala}{Hyderabad, India}{Software Engineer Intern}{Jun 2022 --- Dec 2022}
\begin{cvbullets}
{{ gl_bullets }}
\end{cvbullets}
\section{Education}
\noindent\begin{tabular*}{\textwidth}{@{}l@{\extracolsep{\fill}}r@{}}
\textbf{Southeast Missouri State University} & Cape Girardeau, MO \\[-3pt]
\textit{\small M.S. in Computer Science\ ---\ GPA: 3.9/4.0} & \textit{\small Jan 2024 -- Dec 2025} \\
\end{tabular*}
\section{Technical Projects}
{{ projects_block }}
\section{Publication \& Awards}
\begin{cvbullets}
\item \textbf{Published:} ``UniLLMOps: A Unified Framework for End-to-End LLM Production Systems''\ ---\ Zenodo, DOI: 10.5281/zenodo.19582347 (Apr 2026).
\item \textbf{Published:} ``Real-Time Video Based Vehicle Detection, Counting \& Classification''\ ---\ CVR Journal, June 2023\ \textbar\ \textbf{Award:} 3rd Prize, Project Expo 2K23.
\item \textbf{Certifications:} Prompt Engineering \& Programming with OpenAI --- Columbia Engineering (Mar 2026)\ \textbar\ Python Essentials 1 --- Cisco (Jul 2023)\ \textbar\ Programming Fundamentals --- Duke.
\end{cvbullets}
\end{document}
"""

CL_TEMPLATE = r"""\documentclass[12pt,letterpaper]{article}
\usepackage[T1]{fontenc}
\usepackage[hidelinks]{hyperref}
\usepackage{geometry}
\usepackage{parskip}
\usepackage{microtype}
\geometry{top=1in, bottom=1in, left=1.1in, right=1.1in}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{8pt}
\begin{document}
\begin{center}
{\large\bfseries \href{https://tanaytammineni.vercel.app/}{Tanay Tammineni}}\\[3pt]
\small
tanaytammineni22@gmail.com\ \textbar\ 816-277-9463\ \textbar\ Irving, TX\\[1pt]
\href{https://www.linkedin.com/in/tanay-tammineni/}{LinkedIn}\ \textbar\
\href{https://github.com/TammineniTanay}{GitHub}\ \textbar\
\href{https://tanaytammineni.vercel.app/}{Portfolio}
\end{center}
\vspace{6pt}
\today
\vspace{6pt}
Hiring Manager\\
{{ company }}
\vspace{6pt}
Dear Hiring Manager,
\normalsize

{{ para1 }}

{{ para2 }}

{{ para3 }}

{{ para4 }}

\vspace{8pt}
Sincerely,\\[16pt]
Tanay Tammineni
\end{document}
"""

# ─────────────────────────────────────────────────────────────────────────────
# MORE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def classify_role(title, jd):
    text = (title + " " + (jd or "")[:600]).lower()
    if any(k in text for k in ["fine-tun","model train","pytorch","qlora","research scientist","ml research"]):
        return "ml"
    if any(k in text for k in ["backend","fastapi","websocket","systems engineer","audio","api engineer"]):
        return "backend"
    if any(k in text for k in ["data engineer","etl","databricks","pyspark","analytics engineer",
                                 "data pipeline","data quality","data analytics"]):
        return "data"
    return "default"

def build_projects_block(keys):
    blocks = []
    for i, key in enumerate(keys[:3]):
        p = PROJECT_DATA.get(key)
        if not p:
            continue
        heading = (r"\projheading{" + p["title"] + "}{" +
                   p["url"] + "}{" + p["stack"] + "}")
        block   = (heading + "\n" + r"\begin{cvbullets}" + "\n" +
                   "\n".join(p["bullets"]) + "\n" + r"\end{cvbullets}")
        if i > 0:
            block = r"\vspace{2pt}" + "\n" + block
        blocks.append(block)
    return "\n".join(blocks)

def call_ollama(system, prompt):
    payload = {
        "model": MODEL_NAME, "system": system, "prompt": prompt,
        "stream": True, "options": {"temperature": 0.05, "num_ctx": 3072},
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=None)
        if resp.status_code != 200:
            return None
        print("    Thinking: ", end="", flush=True)
        text, n = "", 0
        for line in resp.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    if "response" in chunk:
                        text += chunk["response"]
                        n += 1
                        if n % 25 == 0:
                            print(".", end="", flush=True)
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
        print(" [DONE]")
        return text.strip()
    except Exception as e:
        print(f"\n    ERROR: {e}")
        return None

def parse_json(raw):
    if not raw:
        return None
    clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
    s, e  = clean.find("{"), clean.rfind("}")
    if s != -1 and e > s:
        clean = clean[s:e+1]
    try:
        return json.loads(clean)
    except Exception:
        return None

def check_pdflatex():
    return shutil.which("pdflatex") is not None

def compile_pdf(tex, out_path):
    out_path = os.path.abspath(out_path)
    tex_file = out_path + ".tex"
    pdf_file = out_path + ".pdf"
    out_dir  = os.path.dirname(tex_file)
    tex_name = os.path.basename(tex_file)
    with open(tex_file, "w", encoding="utf-8") as f:
        f.write(tex)
    try:
        r = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_name],
            capture_output=True, text=True, timeout=60, cwd=out_dir,
        )
        ok = os.path.exists(pdf_file) and r.returncode == 0
        for ext in [".aux", ".log", ".out"]:
            p = out_path + ext
            if os.path.exists(p):
                os.remove(p)
        return ok, r.stdout[-600:] if not ok else ""
    except Exception as ex:
        return False, str(ex)

# ─────────────────────────────────────────────────────────────────────────────
# PROCESS ONE JOB
# ─────────────────────────────────────────────────────────────────────────────

def process_one_job(job_id, company, title, jd_text, conn, is_linkedin=False):
    c = conn.cursor()
    c.execute("SELECT url, status FROM seen_jobs WHERE jobpostingid=?", (job_id,))
    row = c.fetchone()
    url            = row[0] if row else ""
    current_status = row[1] if row else "TO_PROCESS"

    safe   = re.sub(r"[^a-zA-Z0-9_]", "_", f"{company}_{title}")[:55]
    outdir = os.path.join(TODAY_DIR, safe)
    os.makedirs(outdir, exist_ok=True)

    linkedin_tag = " [LinkedIn]" if is_linkedin else ""
    print(f"\n  [{company}] {title}{linkedin_tag}")

    jd_snip = (jd_text or "")[:2500]
    raw     = call_ollama(
        COMBINED_PROMPT,
        f"Job Title: {title}\nCompany: {company}\n\nJob Description:\n{jd_snip}"
    )
    dec = parse_json(raw)

    if not dec:
        print("    JSON parse failed — skipping.")
        with open(os.path.join(outdir, "raw.txt"), "w", encoding="utf-8") as f:
            f.write(raw or "empty")
        write_job_info(outdir, company, title, url, "FAILED", "JSON parse error")
        c.execute("UPDATE seen_jobs SET status='FAILED' WHERE jobpostingid=?", (job_id,))
        conn.commit()
        return "FAILED"

    verdict = dec.get("verdict", "MAYBE").upper()
    reason  = dec.get("reason", "")
    print(f"    Verdict: {verdict} — {reason}")

    with open(os.path.join(outdir, "decision.json"), "w", encoding="utf-8") as f:
        json.dump(dec, f, indent=2)

    write_job_info(outdir, company, title, url, verdict, reason)

    if verdict == "NO" and not is_linkedin:
        c.execute("UPDATE seen_jobs SET status='SKIPPED_NO' WHERE jobpostingid=?", (job_id,))
        conn.commit()
        return "NO"

    # CL paras with retry
    para1 = clean_text(dec.get("cl_para1", ""))
    para2 = clean_text(dec.get("cl_para2", ""))
    para4 = clean_text(dec.get("cl_para4", ""))

    if not para1 or not para2:
        print("    CL paragraphs missing — retrying...")
        raw2 = call_ollama(
            CL_RETRY_PROMPT,
            f"Job Title: {title}\nCompany: {company}\n\nJD:\n{jd_snip[:1500]}"
        )
        dec2 = parse_json(raw2)
        if dec2:
            para1 = para1 or clean_text(dec2.get("cl_para1", ""))
            para2 = para2 or clean_text(dec2.get("cl_para2", ""))
            para4 = para4 or clean_text(dec2.get("cl_para4", ""))

    if not para1:
        para1 = (f"The {title} role at {company} stood out for its focus on "
                 f"production AI systems, which maps directly to the work I have "
                 f"been building over the past year.")
    if not para2:
        para2 = (f"{company}'s applied AI work aligns with my experience building "
                 f"LLM pipelines, RAG systems, and cloud-native ML infrastructure.")
    if not para4:
        para4 = (f"I would welcome the opportunity to discuss how my background "
                 f"aligns with {company}'s engineering goals. "
                 f"I am authorized to work in the U.S.")

    role_type  = classify_role(title, jd_text or "")
    projects   = pick_projects(dec.get("projects", []), jd_text or "")
    closing    = clean_text(dec.get("summary_closing",
                 f"Brings production AI engineering depth to {company}'s technical team."))
    summary_p  = SUMMARY_BODY.get(role_type, SUMMARY_BODY["default"]) + " " + closing
    rows       = TOOLKIT_ROWS.get(role_type, TOOLKIT_ROWS["default"])
    para3      = build_cl_para3(projects)
    vb_bullets = "\n".join([VOICEBOTICS_BULLETS[k]
                             for k in ROLE_VB_MAP.get(role_type, ROLE_VB_MAP["default"])])
    gl_bullets = "\n".join(GLOBALSHALA_BULLETS)
    proj_block = build_projects_block(projects)

    resume_latex = fill_template(RESUME_TEMPLATE,
        summary_paragraph=summary_p,
        skills_row1=rows["row1"], skills_row2=rows["row2"],
        skills_row3=rows["row3"], skills_row4=rows["row4"],
        vb_bullets=vb_bullets, gl_bullets=gl_bullets,
        projects_block=proj_block,
    )
    cl_latex = fill_template(CL_TEMPLATE,
        company=company, para1=para1, para2=para2,
        para3=para3, para4=para4,
    )

    res_path = os.path.join(outdir, "resume")
    cl_path  = os.path.join(outdir, "cover_letter")

    with open(res_path + ".tex", "w", encoding="utf-8") as f:
        f.write(resume_latex)
    with open(cl_path + ".tex", "w", encoding="utf-8") as f:
        f.write(cl_latex)

    if check_pdflatex():
        r_ok, r_err = compile_pdf(resume_latex, res_path)
        c_ok, _     = compile_pdf(cl_latex, cl_path)
        if r_ok and c_ok:
            print(f"    PDFs compiled -> {outdir}/")
        elif r_ok:
            print(f"    Resume PDF ok. CL .tex only -> {outdir}/")
        else:
            print(f"    .tex saved (compile error) -> {outdir}/")
            if r_err:
                print(f"    Hint: {r_err[:120]}")
    else:
        print(f"    .tex saved -> {outdir}/")

    # LinkedIn jobs stay as MANUAL_APPLY
    # Others get GENERATED_YES/MAYBE
    if is_linkedin:
        # keep MANUAL_APPLY status — just update so we know PDF was generated
        c.execute("UPDATE seen_jobs SET status='MANUAL_APPLY' WHERE jobpostingid=?", (job_id,))
    else:
        c.execute("UPDATE seen_jobs SET status=? WHERE jobpostingid=?",
                  (f"GENERATED_{verdict}", job_id))
    conn.commit()
    return verdict

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main(db_path=r"C:\JobAgentData\job_agent.db"):
    os.makedirs(TODAY_DIR, exist_ok=True)
    conn = sqlite3.connect(db_path)
    c    = conn.cursor()

    # auto-retry previously failed jobs
    c.execute("UPDATE seen_jobs SET status='TO_PROCESS' WHERE status='FAILED'")
    conn.commit()

    # get both TO_PROCESS and MANUAL_APPLY (LinkedIn) jobs without PDFs
    c.execute("""
        SELECT jobpostingid, company, title, jd_text, status, url
        FROM seen_jobs
        WHERE status IN ('TO_PROCESS', 'MANUAL_APPLY')
        ORDER BY CASE status WHEN 'TO_PROCESS' THEN 0 ELSE 1 END, date_found DESC
    """)
    all_jobs = c.fetchall()

    # filter out LinkedIn jobs that already have PDFs
    jobs = []
    for row in all_jobs:
        job_id, company, title, jd_text, status, url = row
        safe   = re.sub(r"[^a-zA-Z0-9_]", "_", f"{company}_{title}")[:55]
        # check if PDF already exists in any date folder
        has_pdf = False
        if os.path.isdir(OUTPUT_DIR):
            for dd in os.listdir(OUTPUT_DIR):
                cand = os.path.join(OUTPUT_DIR, dd, safe, "resume.pdf")
                if os.path.exists(cand):
                    has_pdf = True
                    break
        if status == "MANUAL_APPLY" and has_pdf:
            continue   # already has PDF, skip
        jobs.append(row)

    total = len(jobs)

    if not jobs:
        print("No jobs queued.")
        conn.close()
        return {}

    auto_count = sum(1 for j in jobs if j[4] == "TO_PROCESS")
    li_count   = sum(1 for j in jobs if j[4] == "MANUAL_APPLY")
    print(f"\n=== Stage 2: {total} job(s) — saving to {TODAY_DIR}/ ===")
    print(f"  Auto-apply: {auto_count}  |  LinkedIn manual: {li_count}")
    if not check_pdflatex():
        print("NOTE: pdflatex not found — .tex only.\n")

    results = {"YES": 0, "MAYBE": 0, "NO": 0, "FAILED": 0, "LINKEDIN": 0}
    for i, (job_id, company, title, jd_text, status, url) in enumerate(jobs, 1):
        is_li = "linkedin.com" in (url or "").lower() or status == "MANUAL_APPLY"
        print(f"\n[{i}/{total}]", end="")
        v = process_one_job(job_id, company, title, jd_text, conn, is_linkedin=is_li)
        if is_li:
            results["LINKEDIN"] += 1
        else:
            results[v if v in results else "FAILED"] += 1
        if i < total:
            print(f"    Cooling down {JOB_COOLDOWN}s...")
            time.sleep(JOB_COOLDOWN)

    print(f"\n\n=== Stage 2 Done ===")
    for k, v in results.items():
        if v > 0:
            print(f"  {k}: {v}")
    print(f"  Today's output: {os.path.abspath(TODAY_DIR)}/")
    conn.close()
    return results


if __name__ == "__main__":
    main()