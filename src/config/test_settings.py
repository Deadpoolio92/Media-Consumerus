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
