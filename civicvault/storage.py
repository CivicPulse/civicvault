"""Storage backend wiring for Cloudflare R2 (S3 API).

Extracted into a pure function so it can be unit-tested without reloading
Django settings. When no bucket is configured (local dev without R2
credentials), fall back to local filesystem storage.
"""

S3_BACKEND = "storages.backends.s3.S3Storage"
FILESYSTEM_BACKEND = "django.core.files.storage.FileSystemStorage"
STATICFILES_BACKEND = "django.contrib.staticfiles.storage.StaticFilesStorage"


def build_storages(*, bucket, endpoint_url, access_key, secret_key, custom_domain=""):
    """Return a Django STORAGES dict. R2 if a bucket is set, else filesystem.

    `custom_domain` is the public hostname that fronts the bucket (a Cloudflare
    custom domain, e.g. "data.civpulse.org"). When set, `storage.url()` returns
    https://<custom_domain>/<key> — the cached, publicly fetchable address —
    instead of the private S3 API endpoint. Uploads still go through
    `endpoint_url`; only the public read URL changes.
    """
    staticfiles = {"BACKEND": STATICFILES_BACKEND}
    if not bucket:
        return {
            "default": {"BACKEND": FILESYSTEM_BACKEND},
            "staticfiles": staticfiles,
        }
    options = {
        "bucket_name": bucket,
        "endpoint_url": endpoint_url,
        "access_key": access_key,
        "secret_key": secret_key,
        # R2 ignores regions; "auto" is the documented value.
        "region_name": "auto",
        "signature_version": "s3v4",
        # R2 supports both path- and virtual-hosted style; Cloudflare's
        # own SDK examples use path-style, which avoids bucket-name DNS
        # edge cases on the S3 API endpoint.
        "addressing_style": "path",
        "default_acl": None,
        # Public assets are served via Cloudflare cache, not signed URLs.
        "querystring_auth": False,
    }
    if custom_domain:
        # url() -> https://<custom_domain>/<key>, the public Cloudflare address.
        options["custom_domain"] = custom_domain
    return {
        "default": {"BACKEND": S3_BACKEND, "OPTIONS": options},
        "staticfiles": staticfiles,
    }
