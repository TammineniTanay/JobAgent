"""
integrations.py
Cloud and database integration utilities for JobAgent pipeline.
Extends the core pipeline with cloud storage, caching, and notification capabilities.
"""

import os
import json
from datetime import datetime


# ── AWS S3 ────────────────────────────────────────────────────
def backup_database_to_s3(db_path: str, bucket: str):
    """
    Backup the SQLite job database to AWS S3 for disaster recovery.
    Runs nightly to prevent data loss from local OneDrive sync issues.
    
    Args:
        db_path: Local path to SQLite database
        bucket: S3 bucket name for backups
    """
    import boto3
    
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1")
    )
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    key = f"backups/job_agent_{timestamp}.db"
    
    s3.upload_file(db_path, bucket, key)
    print(f"Database backed up to s3://{bucket}/{key}")


# ── DynamoDB ──────────────────────────────────────────────────
def log_application_to_dynamodb(job_title: str, company: str, status: str):
    """
    Log each job application event to DynamoDB for cross-device tracking.
    Useful when running JobAgent on multiple machines.
    
    Args:
        job_title: Title of job applied to
        company: Company name
        status: Application status (applied, rejected, interview, etc.)
    """
    import boto3
    
    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    table = dynamodb.Table("job-agent-applications")
    
    table.put_item(Item={
        "application_id": f"{company}_{job_title}_{datetime.utcnow().isoformat()}",
        "job_title": job_title,
        "company": company,
        "status": status,
        "timestamp": datetime.utcnow().isoformat()
    })


# ── AWS Lambda ────────────────────────────────────────────────
def trigger_lambda_notification(job_count: int, applied_count: int):
    """
    Trigger an AWS Lambda function to send a daily summary notification.
    Decouples notification logic from the main pipeline.
    
    Args:
        job_count: Total jobs discovered today
        applied_count: Jobs successfully applied to today
    """
    import boto3
    
    lambda_client = boto3.client("lambda", region_name=os.getenv("AWS_REGION", "us-east-1"))
    
    payload = {
        "job_count": job_count,
        "applied_count": applied_count,
        "date": datetime.utcnow().strftime("%Y-%m-%d")
    }
    
    lambda_client.invoke(
        FunctionName="job-agent-daily-summary",
        InvocationType="Event",
        Payload=json.dumps(payload)
    )


# ── MongoDB ───────────────────────────────────────────────────
def archive_old_jobs_to_mongodb(jobs: list):
    """
    Archive jobs older than 30 days to MongoDB for historical analysis.
    Keeps the active SQLite database lean while preserving history.
    
    Args:
        jobs: List of job dictionaries to archive
    """
    from pymongo import MongoClient
    
    client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db = client["job_agent_archive"]
    collection = db["historical_jobs"]
    
    if jobs:
        collection.insert_many(jobs)
    
    client.close()


# ── Redis ─────────────────────────────────────────────────────
def cache_company_research(company_name: str, research_data: dict, ttl: int = 86400):
    """
    Cache company research data in Redis to avoid redundant scraping.
    TTL of 24 hours since company info doesn't change frequently.
    
    Args:
        company_name: Company name as cache key
        research_data: Research findings dictionary
        ttl: Time to live in seconds (default 24 hours)
    """
    import redis
    
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True
    )
    
    r.setex(f"company:{company_name}", ttl, json.dumps(research_data))


def get_cached_company_research(company_name: str) -> dict:
    """
    Retrieve cached company research from Redis.
    
    Args:
        company_name: Company name to look up
    
    Returns:
        Cached research data or None if not found
    """
    import redis
    
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True
    )
    
    cached = r.get(f"company:{company_name}")
    return json.loads(cached) if cached else None


# ── GCP Cloud Storage ─────────────────────────────────────────
def export_tracker_to_gcs(html_path: str, bucket_name: str):
    """
    Export the HTML tracker dashboard to Google Cloud Storage.
    Enables viewing the tracker from any device via a public URL.
    
    Args:
        html_path: Local path to tracker.html
        bucket_name: GCS bucket name
    """
    from google.cloud import storage
    
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob("tracker.html")
    
    blob.upload_from_filename(html_path)
    blob.make_public()
    
    print(f"Tracker available at: {blob.public_url}")


# ── Azure Blob Storage ────────────────────────────────────────
def sync_resumes_to_azure(local_dir: str, container_name: str):
    """
    Sync generated resume PDFs to Azure Blob Storage.
    Provides cloud backup independent of local OneDrive sync issues
    that previously caused database corruption.
    
    Args:
        local_dir: Local directory containing resume PDFs
        container_name: Azure container name
    """
    from azure.storage.blob import BlobServiceClient
    
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    
    for filename in os.listdir(local_dir):
        if filename.endswith(".pdf"):
            blob_client = container_client.get_blob_client(filename)
            with open(os.path.join(local_dir, filename), "rb") as data:
                blob_client.upload_blob(data, overwrite=True)