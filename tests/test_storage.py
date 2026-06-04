from civicvault.storage import build_storages

S3_BACKEND = "storages.backends.s3.S3Storage"
FS_BACKEND = "django.core.files.storage.FileSystemStorage"


def test_no_bucket_falls_back_to_filesystem():
    storages = build_storages(bucket="", endpoint_url="", access_key="", secret_key="")
    assert storages["default"]["BACKEND"] == FS_BACKEND


def test_bucket_set_uses_r2_s3_backend():
    storages = build_storages(
        bucket="civicvault-media",
        endpoint_url="https://acct.r2.cloudflarestorage.com",
        access_key="AK",
        secret_key="SK",
    )
    default = storages["default"]
    assert default["BACKEND"] == S3_BACKEND
    opts = default["OPTIONS"]
    assert opts["bucket_name"] == "civicvault-media"
    assert opts["endpoint_url"] == "https://acct.r2.cloudflarestorage.com"
    assert opts["region_name"] == "auto"
    assert opts["addressing_style"] == "path"  # R2-correct; guards the value
    assert opts["default_acl"] is None
    assert opts["querystring_auth"] is False
    # No custom domain unless one is supplied.
    assert "custom_domain" not in opts


def test_custom_domain_sets_public_read_host():
    storages = build_storages(
        bucket="civicvault-media",
        endpoint_url="https://acct.r2.cloudflarestorage.com",
        access_key="AK",
        secret_key="SK",
        custom_domain="data.civpulse.org",
    )
    assert storages["default"]["OPTIONS"]["custom_domain"] == "data.civpulse.org"
