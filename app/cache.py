"""Redis-backed cache-aside layer for short_code -> long_url lookups.

Redirects are the hot path (reads >> writes for a URL shortener), so we cache
resolved long URLs in Redis. On a cache miss we read Postgres and populate the
cache with a TTL. This keeps p99 redirect latency low and shields the database
from read amplification.
"""

import redis

from app.config import settings

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    """Lazily create a shared Redis client (module-level singleton)."""
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def set_client(client) -> None:
    """Inject a client (used by tests to swap in fakeredis)."""
    global _client
    _client = client


def cache_key(short_code: str) -> str:
    return f"url:{short_code}"


def get_long_url(short_code: str) -> str | None:
    return get_client().get(cache_key(short_code))


def set_long_url(short_code: str, long_url: str) -> None:
    get_client().set(cache_key(short_code), long_url, ex=settings.cache_ttl_seconds)
