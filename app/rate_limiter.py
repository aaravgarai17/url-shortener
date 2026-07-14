"""Distributed sliding-window rate limiter backed by Redis sorted sets.

Each client (keyed by IP) gets a sorted set whose members are request
timestamps. On each request we drop entries older than the window, count what
remains, and reject if the count exceeds the limit. Using Redis makes the limit
shared across every app instance — a purely in-process counter would let a
client multiply its quota by the number of replicas.

The read-trim-count-add sequence runs inside a MULTI/EXEC pipeline so it is
atomic per client and safe under concurrency.
"""

import time
import uuid

from app.cache import get_client
from app.config import settings


def is_allowed(identifier: str) -> bool:
    """Return True if the request is within the rate limit, else False."""
    client = get_client()
    key = f"ratelimit:{identifier}"
    now = time.time()
    window_start = now - settings.rate_limit_window_seconds

    pipe = client.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)      # evict old requests
    pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})  # record this one
    pipe.zcard(key)                                   # count in-window requests
    pipe.expire(key, settings.rate_limit_window_seconds)
    _, _, count, _ = pipe.execute()

    return count <= settings.rate_limit_requests
