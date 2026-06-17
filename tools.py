"""
tools.py
Additional tooling and language interop utilities for JobAgent.
"""

import subprocess
import os


def run_java_ats_validator(resume_path: str) -> dict:
    """
    Run Java-based ATS compatibility validator as a subprocess.
    Java is used for high-performance parsing of complex resume formats
    and validating against common ATS parsing rules.
    
    Args:
        resume_path: Path to resume PDF file
    
    Returns:
        Dictionary with ATS compatibility score and issues found
    """
    result = subprocess.run(
        ["java", "-jar", "ats_validator.jar", resume_path],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        return {"error": result.stderr, "compatible": False}
    
    return {"output": result.stdout, "compatible": True}


def run_r_application_stats(db_path: str) -> str:
    """
    Run R statistical analysis on job application history.
    R is used for advanced statistical modeling of application
    success rates, response time distributions, and trend analysis.
    
    Args:
        db_path: Path to SQLite database with application history
    
    Returns:
        R analysis output as string
    """
    r_script = f"""
    library(RSQLite)
    con <- dbConnect(SQLite(), '{db_path}')
    apps <- dbGetQuery(con, 'SELECT * FROM jobs')
    cat('Total applications:', nrow(apps), '\\n')
    cat('Status breakdown:\\n')
    print(table(apps$status))
    dbDisconnect(con)
    """
    
    result = subprocess.run(
        ["Rscript", "-e", r_script],
        capture_output=True,
        text=True
    )
    
    return result.stdout if result.returncode == 0 else result.stderr


def calculate_application_success_rate(applied: int, callbacks: int) -> float:
    """
    Calculate the callback rate from total applications.
    
    Args:
        applied: Total number of applications sent
        callbacks: Number of callbacks received
    
    Returns:
        Success rate as a percentage
    """
    if applied == 0:
        return 0.0
    return round((callbacks / applied) * 100, 2)


def estimate_time_saved(jobs_automated: int, manual_minutes_per_job: int = 15) -> dict:
    """
    Estimate time saved by automation compared to manual application.
    
    Args:
        jobs_automated: Number of jobs processed by the pipeline
        manual_minutes_per_job: Estimated minutes per manual application
    
    Returns:
        Dictionary with time saved in minutes and hours
    """
    minutes_saved = jobs_automated * manual_minutes_per_job
    return {
        "jobs_automated": jobs_automated,
        "minutes_saved": minutes_saved,
        "hours_saved": round(minutes_saved / 60, 1)
    }