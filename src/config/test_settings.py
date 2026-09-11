from fakeredis import FakeRedisConnection

from .settings import *  # noqa: F403

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,  # noqa: F405
        "TIMEOUT": 18000,  # 5 hours
        "OPTIONS": {
            "CONNECTION_POOL_KWARGS": {"connection_class": FakeRedisConnection},
        },
    },
}

CELERY_TASK_ALWAYS_EAGER = True

TESTING = True

# pytest's argv isn't "manage.py test", so settings.py's IS_PROD detection is True
# and it sets ALLAUTH_TRUSTED_CLIENT_IP_HEADER="X-Real-IP". allauth then demands an
# X-Real-IP header on login (which the LiveServerTestCase browser never sends), so
# login fails with "Unable to determine client IP address" and the Playwright
# integration tests time out. Clear it so allauth falls back to REMOTE_ADDR.
ALLAUTH_TRUSTED_CLIENT_IP_HEADER = ""

# Steam API key for testing
STEAM_API_KEY = "test_steam_api_key"

# Playwright tests use LiveServerTestCase, whose threaded server shares the SQLite
# test DB with the test connection. Django's default SQLite test DB is :memory: with
# cache=shared, which is incompatible with the threaded server (flush fails with
# "database table is locked"). Use a file-based test DB, and raise the busy timeout
# so transient write contention waits it out in CI.
_databases = DATABASES  # noqa: F405  (star-imported from settings.py)
if _databases["default"]["ENGINE"].endswith("sqlite3"):
    _databases["default"]["TEST"] = {
        "NAME": str(BASE_DIR / "test_db.sqlite3"),  # noqa: F405
    }
    _databases["default"]["OPTIONS"] = {
        **_databases["default"].get("OPTIONS", {}),
        "timeout": 60,
    }
