"""
Django settings for the Shop ERP backend.

Kernel apps (always installed): core, catalog, inventory, sync.
Pluggable apps (toggled per entity/store via core.ModuleRegistry): receiving,
enquiry, pos, fiscal, payments, notifications, credit, pricing, analytics.
See architecture.txt at the project root for the full design.
"""

import sys
from pathlib import Path

import environ
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
)
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(str(env_file))

_INSECURE_DEV_KEY = 'django-insecure-dev-key-change-in-production'
SECRET_KEY = env('SECRET_KEY', default=_INSECURE_DEV_KEY)
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# Needed for the Django admin and any session-authenticated POST once the
# site is served over HTTPS on a real host (e.g. https://shop.example.com) —
# without this, Django rejects those POSTs as a cross-origin CSRF attempt.
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# DEBUG=True with the placeholder key is an obviously-broken dev state (every
# page shows debug tracebacks) and safe to default to for a fresh clone.
# DEBUG=False with that same placeholder key is the dangerous combination —
# a deploy that forgot to set SECRET_KEY would otherwise come up quietly in
# production with a public, known secret. Fail loudly instead.
if not DEBUG and SECRET_KEY == _INSECURE_DEV_KEY:
    raise ImproperlyConfigured(
        'SECRET_KEY must be set via the environment (or .env) when DEBUG=False. '
        'Refusing to start with the placeholder dev key in a non-debug deployment.',
    )

# HTTPS / security — all off by default and switched on via .env once TLS
# is live, so a fresh server (or local dev) over plain HTTP keeps working.
# nginx (or any TLS-terminating proxy) talks plain HTTP to gunicorn and
# tells us the original scheme via this header; without it Django can't
# tell the request was actually HTTPS and redirect/cookie logic below
# would misfire.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=False)
# Only set once HTTPS is confirmed working end to end, since a wrong HSTS
# value is awkward for visitors to undo.
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False  # keep False: would affect all *.example.com
SECURE_HSTS_PRELOAD = False


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework.authtoken',
    'django_filters',
    'corsheaders',

    # Kernel apps — always installed, never toggled.
    'core',
    'catalog',
    'inventory',
    'sync',

    # Pluggable apps — enabled per entity/store via core.ModuleRegistry.
    'receiving',
    'enquiry',
    'pos',
    'fiscal',
    'payments',
    'notifications',
    'credit',
    'pricing',
    'analytics',
    'reports',
    'imports',
    'audit',
]

AUTH_USER_MODEL = 'core.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# Defaults to a local SQLite file so the project runs with zero setup;
# point DATABASE_URL at Postgres (per architecture.txt's stack) in .env,
# e.g. postgres://user:password@localhost:5432/shop
# An empty DATABASE_URL= (as in .env.example) also falls back to SQLite —
# dj_database_url.config() would return {} for it and Django would refuse
# to start.
DATABASES = {
    'default': dj_database_url.parse(
        env('DATABASE_URL', default='') or f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600,
    )
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Dar_es_Salaam'
USE_I18N = True
USE_TZ = True


# Static files — collectstatic deposits everything here; nginx serves this
# directory directly in production (see deploy/nginx/).

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# User-uploaded files (currently just Entity.logo). Served by Django's
# dev server via config/urls.py when DEBUG; nginx serves this directory
# directly in production (see deploy/nginx/) — gunicorn never does.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Django REST Framework

if 'test' in sys.argv:
    # Real password hashing (deliberately slow) dominated the test run;
    # tests only need passwords to round-trip, not to be strong.
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

REST_FRAMEWORK = {
    # Token first: DRF answers an unauthenticated request with the first
    # class's challenge, and only a 401 (not the 403 session auth gives)
    # makes the frontend send an expired session back to the sign-in page.
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'core.authentication.ExpiringTokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'EXCEPTION_HANDLER': 'config.exceptions.custom_exception_handler',
}


# Sign-in rules (core.authentication): a session lasts TOKEN_TTL_HOURS
# from sign-in — long enough for a shift — and LOGIN_LOCKOUT_ATTEMPTS
# wrong passwords lock that username for LOGIN_LOCKOUT_MINUTES.
TOKEN_TTL_HOURS = env.int('TOKEN_TTL_HOURS', default=14)
LOGIN_LOCKOUT_ATTEMPTS = env.int('LOGIN_LOCKOUT_ATTEMPTS', default=5)
LOGIN_LOCKOUT_MINUTES = env.int('LOGIN_LOCKOUT_MINUTES', default=15)


# CORS — allow the local Vite dev server during development.

CORS_ALLOWED_ORIGINS = env.list(
    'CORS_ALLOWED_ORIGINS',
    default=['http://localhost:5173', 'http://127.0.0.1:5173'],
)


# Email — SMS/Email notification channels are implemented (see
# notifications app); WhatsApp is deferred per architecture.txt.

EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Shop ERP <noreply@localhost>')
SERVER_EMAIL = DEFAULT_FROM_EMAIL


# Error alerts: with ADMINS set (".env: ADMINS=Your Name:you@example.com"),
# every server error (HTTP 500) is emailed to them with the traceback, so
# a crash at the till reaches someone instead of only a log file.
ADMINS = [tuple(a.split(':', 1)) for a in env.list('ADMINS', default=[]) if ':' in a]

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'plain': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        # gunicorn's output goes to journald (see deploy/systemd), so
        # stderr is the log file in production.
        'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'},
        'mail_admins': {'class': 'django.utils.log.AdminEmailHandler', 'level': 'ERROR'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django.request': {'handlers': ['console', 'mail_admins'], 'level': 'ERROR', 'propagate': False},
        # Failed nightly backups and SMS sends log at ERROR from these.
        'core.management': {'handlers': ['console', 'mail_admins'], 'level': 'INFO', 'propagate': False},
        'notifications': {'handlers': ['console', 'mail_admins'], 'level': 'INFO', 'propagate': False},
    },
}


# Backups (core/management/commands/backup.py). BACKUP_DIR empty = backups
# not configured, and /api/health/ doesn't check them.
BACKUP_DIR = env('BACKUP_DIR', default='')
BACKUP_KEEP = env.int('BACKUP_KEEP', default=14)
BACKUP_MAX_AGE_HOURS = env.int('BACKUP_MAX_AGE_HOURS', default=26)


# SMS (notifications/channels/sms_channel.py). SMS_PROVIDER=beem sends
# through Beem Africa (https://beem.africa) with the account's API key and
# secret and an approved sender ID; anything else only logs the message.
SMS_PROVIDER = env('SMS_PROVIDER', default='log')
BEEM_API_KEY = env('BEEM_API_KEY', default='')
BEEM_SECRET_KEY = env('BEEM_SECRET_KEY', default='')
BEEM_SENDER_ID = env('BEEM_SENDER_ID', default='')
