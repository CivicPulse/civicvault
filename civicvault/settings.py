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


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third-party
    "rest_framework",
    # Local
    "core",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
STORAGES = build_storages(
    bucket=env("R2_BUCKET", default=""),
    endpoint_url=env("R2_ENDPOINT_URL", default=""),
    access_key=env("R2_ACCESS_KEY_ID", default=""),
    secret_key=env("R2_SECRET_ACCESS_KEY", default=""),
)

# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
