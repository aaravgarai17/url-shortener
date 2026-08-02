# URL Shortener

A TinyURL/Bitly-style link shortening service built to demonstrate core system
design concepts: **base62 key generation**, a **cache-aside read path**, and a
**distributed sliding-window rate limiter** — deployed as **3 horizontally
scaled replicas behind a load balancer**, instrumented with **Prometheus +
Grafana**, and validated by a **k6 load test** and a **chaos test that kills a
live replica under traffic**.

Runnable locally with a single `docker compose up`.

---

## Architecture

```
                    ┌──────────────┐
      clients ────▶ │  nginx (lb)  │  :8080
                    └──────┬───────┘
                           │  round-robin, retries on replica failure
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
     ┌─────────┐     ┌─────────┐      ┌─────────┐
     │  api-1  │     │  api-2  │      │  api-3  │   stateless FastAPI replicas
     └────┬────┘     └────┬────┘      └────┬────┘   (each exposes /metrics)
          └────────────────┼────────────────┘
                cache-aside │ source of truth
                  ┌─────────┴─────────┐
                  ▼                   ▼
          ┌────────────┐     ┌────────────────┐
          │   Redis    │     │   PostgreSQL   │
          │  (cache)   │     │  urls table    │
          │ rate-limit │     │  + click_count │
          └────────────┘     └────────────────┘

          ┌────────────┐     ┌────────────────┐
          │ Prometheus │────▶│    Grafana     │  :3000
          │   :9090    │     │  (dashboard)   │
          └────────────┘     └────────────────┘
             scrapes each replica individually via Docker DNS
```

Seven services via Docker Compose: **3 API replicas**, an **nginx load
balancer**, Postgres (system of record), Redis (cache + rate limiting), and a
**Prometheus/Grafana** observability stack.

**Why the app tier is stateless.** No request state lives in application
memory — sessions, cache, rate-limit counters, and analytics all live in Redis
or Postgres. That's what makes `--scale api=3` work with no coordination, and
what makes losing a replica a non-event (proven by the chaos test below).

## Key design decisions

**Base62 codes from the primary key.** When a URL is inserted, Postgres assigns
an auto-increment `id`. The short code is `base62(id)`, using the alphabet
`[0-9a-zA-Z]`. Because ids are unique, codes are unique *by construction* — there
is no random generation and no collision-retry loop. A 7-char code covers
62⁷ ≈ 3.5 trillion URLs.

**Cache-aside for redirects.** Redirects vastly outnumber creates, so the read
path is optimized. On `GET /{short_code}` the app checks Redis first; on a miss
it reads Postgres and backfills the cache with a TTL. This keeps redirect
latency low and protects the database from read amplification.

**Distributed rate limiting.** `POST /api/shorten` is protected by a
sliding-window limiter implemented with a Redis sorted set per client IP.
Timestamps are the members; each request trims entries older than the window,
counts what remains, and rejects over-limit requests. The state lives in Redis
so the limit is enforced *across all app replicas* — an in-process counter would
let a client multiply its quota by the number of instances. The trim-count-add
runs in a Redis pipeline for atomicity under concurrency.

**Best-effort analytics.** Each redirect increments `click_count` via a single
`UPDATE`, surfaced through `GET /api/stats/{short_code}`.

## API

| Method | Path                     | Description                          |
| ------ | ------------------------ | ------------------------------------ |
| POST   | `/api/shorten`           | Create a short code for a long URL   |
| GET    | `/{short_code}`          | 301 redirect to the long URL         |
| GET    | `/api/stats/{short_code}`| Click count and metadata             |
| GET    | `/health`                | Liveness probe                       |

Interactive docs are auto-generated at `/docs` (Swagger UI).

## Running locally

**Requires:** Docker Desktop. Optionally [k6](https://k6.io/) for the load test.

```bash
cp .env.example .env
docker compose up --build
```

Starts 3 API replicas plus Postgres, Redis, nginx, Prometheus, and Grafana.

| Service           | URL                     |
| ----------------- | ----------------------- |
| API (via nginx)   | http://localhost:8080   |
| Swagger docs      | http://localhost:8080/docs |
| Prometheus        | http://localhost:9090   |
| Grafana dashboard | http://localhost:3000   |

Grafana auto-provisions the datasource and the **URL Shortener — Service
Health** dashboard; no login or manual setup required.

```bash
# Create
curl -X POST http://localhost:8080/api/shorten \
  -H 'Content-Type: application/json' \
  -d '{"long_url": "https://www.anthropic.com"}'
# -> {"short_code":"1","short_url":"http://localhost:8080/1", ...}

# Redirect (note the X-Instance-Id header — it changes between replicas)
curl -i http://localhost:8080/1

# Watch requests being balanced across all 3 replicas
for i in $(seq 1 6); do
  curl -s -o /dev/null -D - http://localhost:8080/1 | grep -i x-instance-id
done

# Stats
curl http://localhost:8080/api/stats/1
```

## Observability

Each replica exposes `/metrics` in Prometheus format; Prometheus discovers all
replicas through Docker DNS and scrapes them **individually**, so the dashboard
can break traffic down per container rather than blending them together.

Metrics collected:

| Metric                           | Why it matters                                                    |
| -------------------------------- | ----------------------------------------------------------------- |
| `http_requests_total`            | Rate + errors, labeled by endpoint, status, and replica            |
| `http_request_duration_seconds`  | Latency histogram → p50/p95/p99 percentiles                        |
| `cache_events_total`             | Cache hit ratio — the key health signal for a cache-aside design   |
| `redirects_total`                | Business-level throughput                                          |

One deliberate detail: the `endpoint` label uses the **route template**
(`/{short_code}`), not the raw path. Labeling by raw path would mint a new time
series for every short code ever visited — unbounded cardinality is the classic
way to take down a Prometheus server. There's a regression test asserting this.

## Load testing

A [k6](https://k6.io/) script drives the redirect hot path: 20 URLs are created
in setup, then traffic ramps to **200 concurrent virtual users**.

```bash
brew install k6                      # or: docker run --rm -i grafana/k6
k6 run loadtest/redirect_load.js
```

The thresholds are **assertions, not decoration** — the run exits non-zero if
p95 latency exceeds 50ms, p99 exceeds 150ms, or the error rate crosses 1%. That
makes it a performance regression gate you can wire into CI, not just a traffic
generator. Watch the Grafana dashboard while it runs to see latency percentiles
and the per-replica traffic split move in real time.

## Chaos test — surviving replica loss

Most READMEs *claim* "the app tier is stateless so losing an instance is fine."
This one proves it:

```bash
./loadtest/chaos_test.sh
```

The script sends continuous traffic, **kills a live API container mid-flight**,
and asserts the error count stays within tolerance. nginx detects the dead
replica and routes around it; because no request state lived in that
container's memory, the remaining replicas absorb its traffic seamlessly.

```
==> Sending continuous traffic for 30s (killing a replica at 10s)
    !! killing replica a3f9c2e81b04 at t=10s
==> Results
    total requests:  312
    failed requests: 0
RESULT: PASS — survived replica loss (<= 5 failures tolerated)
```

Restore the killed replica with `docker compose up -d --scale api=3`.

## Tests

The unit/integration suite runs with **no external services** — Postgres is
swapped for in-memory SQLite and Redis for `fakeredis`, so it exercises real app
code paths offline.

```bash
pip install -r requirements.txt
pytest -q          # 20 tests
```

Covers base62 round-tripping and collision-freedom, the full API surface,
cache hit/miss accounting, rate limiting, and metric-cardinality safety.

## Scaling notes (how this grows past a laptop)

- **Read scaling:** redirects are served from Redis; add Postgres read replicas
  and a larger cache before the database becomes a bottleneck.
- **Write scaling / distributed IDs:** a single auto-increment column is a write
  bottleneck at scale. Replace it with a range-allocation scheme (each app
  instance leases a block of ids) or a Snowflake-style ID generator, keeping the
  base62 codes.
- **Custom aliases & collisions:** user-chosen codes would need a uniqueness
  check on insert (unique index already enforces it).
- **Analytics at scale:** move click counting off the redirect path into an
  async queue (Kafka) and aggregate, instead of a synchronous `UPDATE`.
- **Availability:** already demonstrated here — 3 stateless replicas behind
  nginx, with the chaos test proving replica loss is survivable. Redis and
  Postgres remain the only stateful components (and the remaining SPOFs; in
  production both would run replicated with automatic failover).

## Project layout

```
url-shortener/
├── app/
│   ├── main.py          # FastAPI app + routes (shorten, redirect, stats)
│   ├── models.py        # SQLAlchemy URL model
│   ├── schemas.py       # Pydantic request/response models
│   ├── base62.py        # id <-> short code encoding
│   ├── cache.py         # Redis cache-aside layer
│   ├── rate_limiter.py  # Redis sliding-window limiter
│   ├── database.py      # engine / session / Base
│   ├── metrics.py       # Prometheus instrumentation + middleware
│   └── config.py        # env-driven settings
├── infra/
│   ├── nginx.conf       # load balancer w/ DNS re-resolution + failover
│   ├── prometheus.yml   # per-replica scrape config via Docker DNS
│   └── grafana/         # auto-provisioned datasource + dashboard JSON
├── loadtest/
│   ├── redirect_load.js # k6 load test w/ pass-fail latency thresholds
│   └── chaos_test.sh    # kills a live replica, asserts zero downtime
├── tests/               # pytest suite (SQLite + fakeredis, no services needed)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
