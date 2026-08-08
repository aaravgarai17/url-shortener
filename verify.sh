#!/usr/bin/env bash
#
# One-command verification: boots the whole stack and proves every claim the
# README makes, then tears it down. Intended for someone who just cloned this
# repo and wants evidence it works without reading anything.
#
# Usage:  ./verify.sh

set -uo pipefail

BASE="http://localhost:8080"
pass=0
fail=0

ok()  { echo "  ✓ $1"; pass=$(( pass + 1 )); }
bad() { echo "  ✗ $1"; fail=$(( fail + 1 )); }

cleanup() {
  echo ""
  echo "Tearing down..."
  docker compose down -v >/dev/null 2>&1
}
trap cleanup EXIT

echo "=================================================="
echo " 0/5  Preflight"
echo "=================================================="

command -v docker >/dev/null 2>&1 || {
  echo "  ✗ docker not found. Install Docker Desktop and start it."; exit 1; }
docker info >/dev/null 2>&1 || {
  echo "  ✗ Docker daemon not running. Launch Docker Desktop and retry."; exit 1; }
ok "docker is available"

if ! python3 -c "import fakeredis, pytest, fastapi" >/dev/null 2>&1; then
  echo "  ✗ Python test dependencies missing."
  echo ""
  echo "    Install them first:"
  echo "      python3 -m venv .venv && source .venv/bin/activate"
  echo "      pip install -r requirements.txt"
  echo ""
  exit 1
fi
ok "python test dependencies present"

# A sibling project (the api-gateway) also binds 8080, so a stale stack is the
# most common reason this script hangs waiting for a service.
for port in 8080 9090 3000; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  ✗ port $port is already in use."
    echo ""
    echo "    Something else is bound to it — most likely another project's"
    echo "    stack. Find and stop it:"
    echo "      docker ps"
    echo "      docker compose -p <that-project> down"
    echo ""
    exit 1
  fi
done
ok "required ports are free (8080, 9090, 3000)"

echo ""
echo "=================================================="
echo " 1/5  Unit tests (no services needed)"
echo "=================================================="
if python3 -m pytest -q 2>&1 | tail -3; then
  ok "test suite passed"
else
  bad "test suite failed"
fi

echo ""
echo "=================================================="
echo " 2/5  Booting the stack (3 replicas + LB + DB + cache)"
echo "=================================================="
if ! docker compose up -d --build >/tmp/us_build.log 2>&1; then
  bad "docker compose failed to start"
  echo ""
  tail -30 /tmp/us_build.log
  exit 1
fi

printf "  waiting for the API"
up=false
for _ in $(seq 1 40); do
  if curl -fs "$BASE/health" >/dev/null 2>&1; then up=true; break; fi
  printf "."
  sleep 2
done
echo ""

if [[ "$up" == true ]]; then
  ok "service is healthy behind the load balancer"
else
  bad "service never came up"
  docker compose logs --tail=30
  echo "Results: $pass passed, $fail failed"
  exit 1
fi

replicas=$(docker compose ps -q api | wc -l | tr -d ' ')
[[ "$replicas" -ge 3 ]] && ok "$replicas API replicas running" \
                        || bad "expected 3 replicas, found $replicas"

echo ""
echo "=================================================="
echo " 3/5  Shorten and redirect work end to end"
echo "=================================================="
resp=$(curl -s -X POST "$BASE/api/shorten" \
  -H 'Content-Type: application/json' \
  -d '{"long_url": "https://example.com/verify-target"}')
code=$(echo "$resp" | sed -n 's/.*"short_code":"\([^"]*\)".*/\1/p')

[[ -n "$code" ]] && ok "created short code: $code" \
                 || { bad "could not create a short code (got: $resp)"; }

if [[ -n "$code" ]]; then
  status=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/$code")
  [[ "$status" == "301" ]] && ok "redirect returns 301" \
                           || bad "expected 301, got $status"

  loc=$(curl -s -o /dev/null -D - "$BASE/$code" | grep -i '^location:' | tr -d '\r')
  echo "$loc" | grep -q "example.com/verify-target" \
    && ok "redirect points at the original URL" \
    || bad "wrong location header: $loc"

  status=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/doesnotexist")
  [[ "$status" == "404" ]] && ok "unknown code returns 404" \
                           || bad "expected 404, got $status"
fi

echo ""
echo "=================================================="
echo " 4/5  Load balancer distributes across replicas"
echo "=================================================="
ids=$(for _ in $(seq 1 12); do
  curl -s -o /dev/null -D - "$BASE/$code" | grep -i '^x-instance-id:' | awk '{print $2}' | tr -d '\r'
done | sort -u | wc -l | tr -d ' ')

[[ "$ids" -ge 2 ]] && ok "traffic served by $ids distinct replicas" \
                   || bad "all requests hit a single replica ($ids seen)"

echo ""
echo "=================================================="
echo " 5/5  Cache-aside behaviour is observable"
echo "=================================================="
docker compose exec -T cache redis-cli FLUSHALL >/dev/null 2>&1
curl -s -o /dev/null "$BASE/$code"     # forced miss -> repopulates
for _ in $(seq 1 5); do curl -s -o /dev/null "$BASE/$code"; done

events=$(for c in $(docker compose ps -q api); do
  docker exec "$c" sh -c 'curl -s localhost:8000/metrics' 2>/dev/null \
    | grep '^cache_events_total'
done)

echo "$events" | grep -q 'result="hit"'  && ok "cache hits recorded" \
                                         || bad "no cache hits recorded"
echo "$events" | grep -q 'result="miss"' && ok "cache misses recorded" \
                                         || bad "no cache misses recorded"

key=$(docker compose exec -T cache redis-cli KEYS "url:$code" 2>/dev/null | tr -d '\r')
[[ -n "$key" ]] && ok "long URL is cached in Redis ($key)" \
                || bad "expected a cached key for $code"

echo ""
echo "=================================================="
echo " Results: $pass passed, $fail failed"
echo "=================================================="
[[ $fail -eq 0 ]] && echo "VERIFIED — every README claim checks out." \
                  || echo "FAILED — see above."
exit $(( fail > 0 ? 1 : 0 ))
