"""Prometheus metrics.

Exposes the four things you actually want on a dashboard for this service:

  * request rate + latency, sliced by endpoint and status (the "RED" method:
    Rate, Errors, Duration)
  * cache hit/miss ratio — the single most important health signal for a
    cache-aside architecture. If this ratio drops, Postgres load spikes.
  * which instance served the request (`instance_id` label), so a multi-replica
    deployment can be seen actually load-balancing rather than assumed to be.

`multiprocess` mode is not used: each replica is a separate container with its
own /metrics endpoint, and Prometheus scrapes them individually. That is the
correct model for containerized deployments and it is what makes the
per-instance breakdown possible.
"""

import os
import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Identifies which replica served a request. Docker sets HOSTNAME to the
# container id, which gives us a stable per-replica label for free.
INSTANCE_ID = os.getenv("HOSTNAME", "local")

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status", "instance_id"],
)

LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint", "instance_id"],
    # Buckets tuned for a service whose p99 target is well under 100ms.
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

CACHE_EVENTS = Counter(
    "cache_events_total",
    "Cache hits and misses on the redirect path",
    ["result", "instance_id"],
)

REDIRECTS = Counter(
    "redirects_total",
    "Successful short-code redirects served",
    ["instance_id"],
)


def record_cache_hit() -> None:
    CACHE_EVENTS.labels(result="hit", instance_id=INSTANCE_ID).inc()


def record_cache_miss() -> None:
    CACHE_EVENTS.labels(result="miss", instance_id=INSTANCE_ID).inc()


def record_redirect() -> None:
    REDIRECTS.labels(instance_id=INSTANCE_ID).inc()


def _endpoint_label(request) -> str:
    """Use the route template (e.g. '/{short_code}') rather than the raw path.

    Labeling with the raw path would create a new time series per short code —
    unbounded cardinality, which is the classic way to melt a Prometheus server.
    """
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        endpoint = _endpoint_label(request)
        REQUESTS.labels(
            method=request.method,
            endpoint=endpoint,
            status=str(response.status_code),
            instance_id=INSTANCE_ID,
        ).inc()
        LATENCY.labels(
            method=request.method,
            endpoint=endpoint,
            instance_id=INSTANCE_ID,
        ).observe(elapsed)

        # Makes it obvious in curl/browser which replica answered.
        response.headers["X-Instance-Id"] = INSTANCE_ID
        return response


def metrics_endpoint() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
