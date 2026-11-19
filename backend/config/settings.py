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

# DEBUG is off unless .env switches it on: a production server whose
# .env forgot the line must not come up showing tracebacks.
env = environ.Env(
    DEBUG=(bool, False),
)
TESTING = 'test' in sys.argv
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
if not DEBUG and SECRET_KEY == _INSECURE_DEV_KEY and not TESTING:
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
# Cookies (Django admin sign-in, CSRF) only over HTTPS unless DEBUG. The app
# itself uses a token, not cookies. To use /admin/ on a new server before
# TLS is set up, set both to False in .env for the time being.
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True
# An admin session ends when the browser closes, and after 2 hours anyway.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = env.int('SESSION_COOKIE_AGE', default=2 * 60 * 60)
# Only set once HTTPS is confirmed working end to end, since a wrong HSTS
# value is awkward for visitors to undo.
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False  # keep False: would affect all *.example.com
SECURE_HSTS_PRELOAD = False
# `check --deploy` (run in CI with --fail-level WARNING) warns about the two
# lines above; they are deliberate, so only those two warnings are silenced.
SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']


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
    'controlled_substances',
    'pricing',
    'analytics',
    'reports',
    'imports',
    'audit',

    # Composition — features spanning several modules. Nothing imports these.
    'onboarding',
]

AUTH_USER_MODEL = 'core.User'

MIDDLEWARE = [
    # First, so every log line of the request carries its id (core.request_id).
    'core.request_id.RequestIdMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Answers in the language the app asks for (Accept-Language: sw / en).
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Roles and feature switches read once per request (core.request_cache).
    'core.request_cache.RequestCacheMiddleware',
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
if DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
    # SQLite ignores select_for_update(), which receipt numbering and stock
    # movements rely on to serialize two tills. IMMEDIATE transactions take
    # the write lock when the transaction starts instead, so concurrent
    # sales queue up (for up to `timeout` seconds) rather than both reading
    # the same stock or the same last receipt number. Postgres needs neither.
    DATABASES['default'].setdefault('OPTIONS', {}).update({'transaction_mode': 'IMMEDIATE', 'timeout': 20})

# Optional read replica (a streaming copy of the Postgres primary). Reports
# and analytics read from it (core.db_routing.on_replica); everything else,
# and every write, uses the primary. Unset = everything on the primary.
# DATABASE_REPLICA_URL=postgres://shop_ro:<password>@replica-host:5432/shop
if env('DATABASE_REPLICA_URL', default=''):
    DATABASES['replica'] = dj_database_url.parse(env('DATABASE_REPLICA_URL'), conn_max_age=600)
    DATABASES['replica']['TEST'] = {'MIRROR': 'default'}
DATABASE_ROUTERS = ['core.db_routing.ReplicaRouter']


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
LANGUAGES = [('en', 'English'), ('sw', 'Kiswahili')]
# Kiswahili for our own messages and for Django/DRF's built-in ones (DRF
# ships no Swahili). Edit locale/sw/LC_MESSAGES/django.po, then run
# `python manage.py compile_translations`.
LOCALE_PATHS = [BASE_DIR / 'locale']
TIME_ZONE = 'Africa/Dar_es_Salaam'
USE_I18N = True
USE_TZ = True


# Cache: the till's copy of each shop's catalog (pos.views.TillSnapshotView)
# is kept here. The default keeps it in each server process's own memory,
# which is right for one server; with several servers, point CACHE_URL at
# a shared cache such as Redis (redis://localhost:6379/1).
# Entries are keyed by the shop's catalog revision, so a stale one is never
# served, only left to expire.
CACHES = {
    'default': env.cache('CACHE_URL') if env('CACHE_URL', default='') else {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'shop',
        # ~1 MB per shop with 3,000 products; the least recently used go first.
        'OPTIONS': {'MAX_ENTRIES': env.int('CACHE_MAX_ENTRIES', default=200)},
    },
}


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
    # A ceiling against runaway clients (a retry loop, a scraper), far above
    # what a busy till does: a till catching up on a backlog of offline
    # sales sends a few a second, and treats a 429 as "try again later",
    # so a sale is never lost to this. Counted in the cache, so per process
    # with the default in-memory cache and exact once CACHE_URL is Redis.
    # Sign-in, sign-up and SMS codes have their own stricter limits.
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': env('THROTTLE_USER_RATE', default='1200/min'),
        'anon': env('THROTTLE_ANON_RATE', default='120/min'),
    },
    # The anonymous ceiling is per address. nginx appends the real client
    # address to X-Forwarded-For, so the last entry is the one to trust;
    # with no proxy in front (dev server) DRF uses the socket address.
    # One more for each further proxy (e.g. 2 behind Cloudflare + nginx).
    'NUM_PROXIES': env.int('NUM_PROXIES', default=1),
}
if TESTING:
    # Tests make many requests as the same user from the same address.
    REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] = []


# Sign-in rules (core.authentication, core.login_guard): a session lasts
# TOKEN_TTL_HOURS from sign-in — long enough for a shift. Over
# LOGIN_LOCKOUT_MINUTES, LOGIN_LOCKOUT_ATTEMPTS wrong passwords for one
# username from one address lock it there, LOGIN_LOCKOUT_GLOBAL_ATTEMPTS
# from anywhere lock it everywhere, and LOGIN_IP_LOCKOUT_ATTEMPTS from
# one address (any usernames) block that address. Wrong manager
# passwords typed in at the till count too. AUTH_THROTTLE_RATE caps
# requests per address to sign-in, sign-up and password reset.
TOKEN_TTL_HOURS = env.int('TOKEN_TTL_HOURS', default=14)
LOGIN_LOCKOUT_ATTEMPTS = env.int('LOGIN_LOCKOUT_ATTEMPTS', default=5)
LOGIN_LOCKOUT_GLOBAL_ATTEMPTS = env.int('LOGIN_LOCKOUT_GLOBAL_ATTEMPTS', default=20)
LOGIN_IP_LOCKOUT_ATTEMPTS = env.int('LOGIN_IP_LOCKOUT_ATTEMPTS', default=30)
LOGIN_LOCKOUT_MINUTES = env.int('LOGIN_LOCKOUT_MINUTES', default=15)

# The platform administrator (a superuser) sees every shop: their
# sessions are shorter.
SUPERUSER_TOKEN_TTL_HOURS = env.int('SUPERUSER_TOKEN_TTL_HOURS', default=4)
AUTH_THROTTLE_RATE = None if TESTING else env('AUTH_THROTTLE_RATE', default='30/min')

# Offline sales (pos.audit): one dated more than OFFLINE_SALE_CLOCK_GRACE_MINUTES
# outside the shift it names, or more than OFFLINE_SALE_MAX_AGE_HOURS old,
# is kept but reported to the owner (audit.alerts).
OFFLINE_SALE_CLOCK_GRACE_MINUTES = env.int('OFFLINE_SALE_CLOCK_GRACE_MINUTES', default=15)
OFFLINE_SALE_MAX_AGE_HOURS = env.int('OFFLINE_SALE_MAX_AGE_HOURS', default=48)

# Security alerts (audit.alerts, `manage.py send_security_alerts`, every
# 5 minutes from deploy/systemd/shop-security-alerts.timer): owners get
# an SMS (and an email, if they have one) about offline sales at changed
# prices or over a limit, accounts locked by wrong passwords, and a new
# owner added to their shop. Blocked addresses go to ADMINS.
SECURITY_ALERTS_LOOKBACK_HOURS = env.int('SECURITY_ALERTS_LOOKBACK_HOURS', default=24)

# Shops sign themselves up (core.signup) and users reset a forgotten
# password with a code sent by SMS (core.phone_codes). A code lasts
# PHONE_CODE_MINUTES and allows PHONE_CODE_ATTEMPTS guesses; a number gets
# at most PHONE_CODE_PER_PHONE_HOURLY codes an hour and one address
# PHONE_CODE_PER_IP_HOURLY. SIGNUP_OPEN=False closes the public sign-up
# page (shops are then registered in the platform console only).
SIGNUP_OPEN = env.bool('SIGNUP_OPEN', default=True)
PHONE_CODE_MINUTES = env.int('PHONE_CODE_MINUTES', default=10)
PHONE_CODE_ATTEMPTS = env.int('PHONE_CODE_ATTEMPTS', default=5)
PHONE_CODE_PER_PHONE_HOURLY = env.int('PHONE_CODE_PER_PHONE_HOURLY', default=4)
PHONE_CODE_PER_IP_HOURLY = env.int('PHONE_CODE_PER_IP_HOURLY', default=20)
# A development server whose SMS_BACKEND sends nothing (noop/console) shows
# the code on screen instead, but only when this is switched on as well:
# that answer hands anyone the code for any account's password reset.
# Refused outright with DEBUG off.
SHOW_SMS_CODES = env.bool('SHOW_SMS_CODES', default=False)
if SHOW_SMS_CODES and not DEBUG:
    raise ImproperlyConfigured('SHOW_SMS_CODES=True is only allowed with DEBUG=True: it puts every SMS code in the API response.')


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
    'filters': {
        'request_id': {'()': 'core.request_id.RequestIdFilter'},
    },
    'formatters': {
        'plain': {'format': '{asctime} {levelname} [{request_id}] {name}: {message}', 'style': '{'},
    },
    'handlers': {
        # gunicorn's output goes to journald (see deploy/systemd), so
        # stderr is the log file in production.
        'console': {'class': 'logging.StreamHandler', 'formatter': 'plain', 'filters': ['request_id']},
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


# SMS (notifications/sms_backends.py). SMS_BACKEND picks the provider:
#   noop           saves the rows in the delivery log, sends nothing (default)
#   console        same, and writes each message to the log
#   notify_africa  sends through Notify Africa (bearer token + numeric sender ID)
#   beem           sends through Beem Africa (API key + secret + sender name)
# `manage.py check` fails if the chosen provider's credentials are missing.
# The older SMS_PROVIDER=beem still selects Beem when SMS_BACKEND is unset.
# The kernel sends one-time codes through this (core/sms.py), so it needn't
# import the notifications module.
SMS_GATEWAY = 'notifications.sms_backends.get_sms_backend'
SMS_BACKEND = env('SMS_BACKEND', default='beem' if env('SMS_PROVIDER', default='') == 'beem' else 'noop')
NOTIFY_AFRICA_BASE_URL = env('NOTIFY_AFRICA_BASE_URL', default='https://api.notify.africa')
NOTIFY_AFRICA_API_TOKEN = env('NOTIFY_AFRICA_API_TOKEN', default='')
NOTIFY_AFRICA_SENDER_ID = env('NOTIFY_AFRICA_SENDER_ID', default='')
NOTIFY_AFRICA_TIMEOUT = env.int('NOTIFY_AFRICA_TIMEOUT', default=15)
BEEM_API_KEY = env('BEEM_API_KEY', default='')
BEEM_SECRET_KEY = env('BEEM_SECRET_KEY', default='')
BEEM_SENDER_ID = env('BEEM_SENDER_ID', default='')
SMS_MAX_SEGMENTS = env.int('SMS_MAX_SEGMENTS', default=3)  # longer messages are skipped
SMS_BATCH_RECIPIENT_CAP = env.int('SMS_BATCH_RECIPIENT_CAP', default=500)
SMS_PROVIDER_CHUNK_SIZE = env.int('SMS_PROVIDER_CHUNK_SIZE', default=100)
SMS_PROVIDER_CHUNK_SLEEP = env.float('SMS_PROVIDER_CHUNK_SLEEP', default=1.0)
SMS_PRICE_PER_SEGMENT = env.float('SMS_PRICE_PER_SEGMENT', default=0)  # TZS; 0 hides the cost estimate
# When the end-of-day emails, and the SMS of owners without their own time
# (Shops console), go out: HH:MM, TIME_ZONE. The timer runs every 5 minutes.
DAILY_SUMMARY_TIME = env('DAILY_SUMMARY_TIME', default='21:30')
