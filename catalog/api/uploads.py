"""R2 presigned-PUT generation for the ingest API. Builds a boto3 S3 client from
the R2 settings and signs PUT URLs that target the R2 S3 endpoint directly, so
the local tool uploads large media without it transiting the app pod. Idempotent:
keys already present in the bucket are skipped (mirrors ingest.storage)."""

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.files.storage import default_storage


def remote_storage_available() -> bool:
    """False when no R2 bucket is configured (local filesystem fallback).

    Uses settings.R2_BUCKET rather than isinstance(default_storage,
    FileSystemStorage) because default_storage is built once at app load and
    cannot be toggled by a settings fixture in tests. Both checks are
    equivalent in production (R2_BUCKET set <=> default_storage is S3Storage).
    """
    return bool(settings.R2_BUCKET)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def presign_uploads(keys) -> dict:
    client = _client()
    bucket = settings.R2_BUCKET
    ttl = settings.INGEST_UPLOAD_URL_TTL
    uploads, skipped = [], []
    for key in keys:
        if default_storage.exists(key):
            skipped.append(key)
            continue
        url = client.generate_presigned_url(
            "put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl
        )
        uploads.append({"key": key, "url": url, "expires_in": ttl})
    return {"uploads": uploads, "skipped": skipped}
