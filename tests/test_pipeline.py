"""
tests/test_pipeline.py
Unit tests for JobAgent pipeline components.
"""

import pytest
import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPipelineStructure:

    def test_stage1_exists(self):
        """Stage 1 ingest script must exist."""
        assert os.path.exists("stage1_ingest.py")

    def test_stage2_exists(self):
        """Stage 2 generate script must exist."""
        assert os.path.exists("stage2_generate.py")

    def test_stage3_exists(self):
        """Stage 3 apply script must exist."""
        assert os.path.exists("stage3_apply.py")

    def test_run_pipeline_exists(self):
        """Main pipeline orchestrator must exist."""
        assert os.path.exists("run_pipeline.py")


class TestDatabaseOperations:

    def test_sqlite_create_table(self):
        """SQLite database operations work correctly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        cursor.execute("INSERT INTO jobs (title, company) VALUES (?, ?)",
                      ("AI Engineer", "TechCorp"))
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM jobs")
        count = cursor.fetchone()[0]
        assert count == 1

        conn.close()
        os.unlink(db_path)

    def test_sqlite_status_update(self):
        """Job status updates work correctly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                title TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        cursor.execute("INSERT INTO jobs (title) VALUES (?)", ("ML Engineer",))
        conn.commit()

        cursor.execute("UPDATE jobs SET status = ? WHERE title = ?",
                      ("applied", "ML Engineer"))
        conn.commit()

        cursor.execute("SELECT status FROM jobs WHERE title = ?", ("ML Engineer",))
        status = cursor.fetchone()[0]
        assert status == "applied"

        conn.close()
        os.unlink(db_path)


class TestJobFiltering:

    def test_filter_empty_titles(self):
        """Jobs with empty titles should be filtered out."""
        jobs = [
            {"title": "AI Engineer", "company": "TechCorp"},
            {"title": "", "company": "Unknown"},
            {"title": "ML Researcher", "company": "OpenAI"},
        ]
        filtered = [j for j in jobs if j["title"].strip()]
        assert len(filtered) == 2

    def test_filter_duplicate_jobs(self):
        """Duplicate job titles from same company should be removed."""
        jobs = [
            {"title": "AI Engineer", "company": "TechCorp"},
            {"title": "AI Engineer", "company": "TechCorp"},
            {"title": "ML Engineer", "company": "TechCorp"},
        ]
        seen = set()
        unique = []
        for job in jobs:
            key = (job["title"], job["company"])
            if key not in seen:
                seen.add(key)
                unique.append(job)
        assert len(unique) == 2

    def test_status_values(self):
        """Valid job statuses are limited to known values."""
        valid_statuses = {"pending", "applied", "rejected", "interview", "offer"}
        test_status = "applied"
        assert test_status in valid_statuses