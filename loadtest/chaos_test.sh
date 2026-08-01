#!/usr/bin/env bash
#
# Chaos test: kill an API replica while it is serving live traffic and verify
# the system keeps serving requests.
#
# The claim being tested is the one every README makes and few prove: "the app
# tier is stateless, so losing a replica is a non-event." Because all shared
# state lives in Postgres and Redis (not in app memory), nginx simply routes
# around the dead container and in-flight requests are retried against a
# healthy one.
#
# Usage:  ./loadtest/chaos_test.sh
# Expects: docker compose up --scale api=3   (already running)

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
DURATION="${DURATION:-30}"       # total seconds of traffic
KILL_AT="${KILL_AT:-10}"         # seconds in before killing a replica

echo "==> Creating a short code to hammer"
SHORT_CODE=$(curl -s -X POST "$BASE_URL/api/shorten" \
  -H 'Content-Type: application/json' \
  -d '{"long_url": "https://example.com/chaos"}' | sed -n 's/.*"short_code":"\([^"]*\)".*/\1/p')

if [[ -z "$SHORT_CODE" ]]; then
  echo "FAILED: could not create a short code. Is the stack running?"
  exit 1
fi
echo "    short_code=$SHORT_CODE"

TOTAL=0
FAILED=0
KILLED=false
START=$(date +%s)

echo "==> Sending continuous traffic for ${DURATION}s (killing a replica at ${KILL_AT}s)"
while true; do
  NOW=$(date +%s)
  ELAPSED=$(( NOW - START ))
  [[ $ELAPSED -ge $DURATION ]] && break

  if [[ "$KILLED" == false && $ELAPSED -ge $KILL_AT ]]; then
    VICTIM=$(docker compose ps -q api | head -1)
    echo ""
    echo "    !! killing replica ${VICTIM:0:12} at t=${ELAPSED}s"
    docker kill "$VICTIM" >/dev/null 2>&1
    KILLED=true
  fi

  STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$BASE_URL/$SHORT_CODE")
  TOTAL=$(( TOTAL + 1 ))
  # 301 is the success case for a redirect.
  if [[ "$STATUS" != "301" ]]; then
    FAILED=$(( FAILED + 1 ))
    echo "    request failed at t=${ELAPSED}s (status=$STATUS)"
  fi
done

echo ""
echo "==> Results"
echo "    total requests:  $TOTAL"
echo "    failed requests: $FAILED"

if [[ $TOTAL -eq 0 ]]; then
  echo "RESULT: INCONCLUSIVE (no requests sent)"
  exit 1
fi

# Allow a tiny grace window: requests already in flight on the killed container
# may fail before nginx marks it down.
THRESHOLD=$(( TOTAL / 100 + 2 ))
if [[ $FAILED -le $THRESHOLD ]]; then
  echo "RESULT: PASS — survived replica loss (<= $THRESHOLD failures tolerated)"
  echo ""
  echo "Bring the killed replica back with:  docker compose up -d --scale api=3"
  exit 0
else
  echo "RESULT: FAIL — $FAILED failures exceeds tolerance of $THRESHOLD"
  exit 1
fi
