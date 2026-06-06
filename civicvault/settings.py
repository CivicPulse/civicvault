"""
Django settings for civicvault project.

Configuration is driven by environment variables (12-factor) via django-environ,
so the same settings module runs on local SQLite and production Postgres with no
code changes — only the environment differs. A local `.env` file (gitignored) is
read if present; see `.env.example` for the available knobs.

For the full list of settings and their values, see
https://docs.djangoproject.com/en/6.0/ref/settings/
"""

from pathlib import Path

import environ

from civicvault.storage import build_storages

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    # (cast, default) — anything not set in the environment falls back to these.
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)

# Read a local .env file if one exists (never committed). Production injects real
# environment variables instead, so this is a no-op there.
environ.Env.read_env(BASE_DIR / ".env")


# SECURITY WARNING: keep the secret key used in production secret!
# The default below is for local development only; production must set SECRET_KEY.
SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-(o#f3g$^@e%n)nr^x!-u9p!7am@ruq&&)q1vj%09do0bw(i2ec",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Behind the cloudflared tunnel → Traefik, the pod serves plain HTTP on :80 while
# TLS terminates at Cloudflare's edge. Trust the proxy's X-Forwarded-Proto so
# Django knows the original request was HTTPS (correct URL building, secure
# cookies, CSRF). Traefik sets this header; only trusted proxies reach the pod.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Scheme-qualified origins allowed to send POSTs (admin, forms) through the proxy.
# Production: CSRF_TRUSTED_ORIGINS=https://vault.civpulse.org
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    # Third-party
    "rest_framework",
    # Local
    "core",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves STATIC_ROOT directly from the app pod (no separate web server /
    # CDN needed for static assets). Must sit right after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "civicvault.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "civicvault.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
# Defaults to local SQLite; set DATABASE_URL (e.g. postgres://...) to override.
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-us"

# Bibb County, GA — store in UTC, present in local time.
TIME_ZONE = "America/New_York"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Object storage (Cloudflare R2 via the S3 API; R2 has zero egress fees).
# Unset R2_BUCKET → local filesystem storage so dev works without credentials.
R2_BUCKET = env("R2_BUCKET", default="")
R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
# Public hostname fronting the bucket (Cloudflare). Makes storage.url()
# return the cached, publicly fetchable address for media.
R2_CUSTOM_DOMAIN = env("R2_CUSTOM_DOMAIN", default="")

STORAGES = build_storages(
    bucket=R2_BUCKET,
    endpoint_url=R2_ENDPOINT_URL,
    access_key=R2_ACCESS_KEY_ID,
    secret_key=R2_SECRET_ACCESS_KEY,
    custom_domain=R2_CUSTOM_DOMAIN,
)

# Remote ingest API (catalog/api). The token authenticates the local push tool;
# unset → the API denies every request. Presigned upload URLs expire after TTL.
INGEST_API_TOKEN = env("INGEST_API_TOKEN", default="")
INGEST_UPLOAD_URL_TTL = env.int("INGEST_UPLOAD_URL_TTL", default=3600)

# In production (DEBUG off) WhiteNoise serves static assets with content-hashed
# filenames + compression for far-future caching. This backend needs a manifest
# built by `collectstatic`, so keep the plain backend in DEBUG (dev/tests) where
# Django's staticfiles app serves files directly and no manifest exists.
if not DEBUG:
    STORAGES["staticfiles"] = {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }

# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
