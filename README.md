# URL Shortener

A TinyURL/Bitly-style link shortening service built to demonstrate core system
design concepts: **base62 key generation**, a **cache-aside read path**, and a
**distributed sliding-window rate limiter**. Written in Python (FastAPI) and
runnable locally with a single `docker compose up`.

---

## Architecture

```
                          ┌──────────────────────────┐
   POST /api/shorten ───▶ │                          │
   GET  /{short_code} ──▶ │       FastAPI  (api)      │
   GET  /api/stats/... ─▶ │                          │
                          └───────┬──────────┬───────┘
                                  │          │
                     cache-aside  │          │  source of truth
                                  ▼          ▼
                          ┌────────────┐  ┌────────────────┐
                          │   Redis    │  │   PostgreSQL   │
                          │  (cache)   │  │  urls table    │
                          │            │  │  + click_count │
                          │ rate-limit │  └────────────────┘
                          │ sorted set │
                          └────────────┘
```

Three services, orchestrated by Docker Compose: the FastAPI app, Postgres (the
system of record), and Redis (cache + rate-limit store).

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

```bash
cp .env.example .env
docker compose up --build
```

The API is then available at http://localhost:8000 (try http://localhost:8000/docs).

Example:

```bash
# Create
curl -X POST http://localhost:8000/api/shorten \
  -H 'Content-Type: application/json' \
  -d '{"long_url": "https://www.anthropic.com"}'
# -> {"short_code":"1","short_url":"http://localhost:8000/1", ...}

# Redirect
curl -i http://localhost:8000/1

# Stats
curl http://localhost:8000/api/stats/1
```

## Tests

Tests run with **no external services** — Postgres is swapped for in-memory
SQLite and Redis for `fakeredis`, so the suite exercises real app code paths
offline.

```bash
pip install -r requirements.txt
pytest -q
```

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
- **Availability:** run multiple stateless API replicas behind a load balancer;
  Redis and Postgres are the only stateful components.

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
│   └── config.py        # env-driven settings
├── tests/               # pytest suite (SQLite + fakeredis, no services needed)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
