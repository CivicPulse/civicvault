"""Storage backend wiring for Cloudflare R2 (S3 API).

Extracted into a pure function so it can be unit-tested without reloading
Django settings. When no bucket is configured (local dev without R2
credentials), fall back to local filesystem storage.
"""

S3_BACKEND = "storages.backends.s3.S3Storage"
FILESYSTEM_BACKEND = "django.core.files.storage.FileSystemStorage"
STATICFILES_BACKEND = "django.contrib.staticfiles.storage.StaticFilesStorage"


def build_storages(*, bucket, endpoint_url, access_key, secret_key):
    """Return a Django STORAGES dict. R2 if a bucket is set, else filesystem."""
    staticfiles = {"BACKEND": STATICFILES_BACKEND}
    if not bucket:
        return {
            "default": {"BACKEND": FILESYSTEM_BACKEND},
            "staticfiles": staticfiles,
        }
    return {
        "default": {
            "BACKEND": S3_BACKEND,
            "OPTIONS": {
                "bucket_name": bucket,
                "endpoint_url": endpoint_url,
                "access_key": access_key,
                "secret_key": secret_key,
                # R2 ignores regions; "auto" is the documented value.
                "region_name": "auto",
                "signature_version": "s3v4",
                "addressing_style": "virtual",
                "default_acl": None,
                # Public assets are served via Cloudflare cache, not signed URLs.
                "querystring_auth": False,
            },
        },
        "staticfiles": staticfiles,
    }
