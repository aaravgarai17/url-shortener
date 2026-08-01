/**
 * k6 load test — redirect hot path.
 *
 * Models realistic traffic for a link shortener: a small number of URLs are
 * created up front (setup), then a large volume of concurrent readers resolve
 * them. Reads dominate writes by design, which is exactly the access pattern
 * the cache-aside architecture is built for.
 *
 * Thresholds are assertions, not decoration: the test FAILS (non-zero exit) if
 * p95 latency regresses past 50ms or the error rate exceeds 1%. That makes this
 * a performance regression gate, not just a traffic generator.
 *
 * Run:  k6 run loadtest/redirect_load.js
 *       k6 run -e BASE_URL=http://localhost:8080 loadtest/redirect_load.js
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";

// Track how many distinct replicas served traffic — proves load balancing.
const instancesSeen = new Counter("instances_seen");
const redirectSuccess = new Rate("redirect_success");

export const options = {
  scenarios: {
    // Ramp up, hold, ramp down — a standard load profile.
    redirect_traffic: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "20s", target: 50 },   // ramp to 50 concurrent users
        { duration: "60s", target: 200 },  // push to 200
        { duration: "30s", target: 200 },  // hold at peak
        { duration: "20s", target: 0 },    // ramp down
      ],
      gracefulRampDown: "10s",
    },
  },
  thresholds: {
    // p95 under 50ms, p99 under 150ms on the cached redirect path.
    "http_req_duration{expected_response:true}": ["p(95)<50", "p(99)<150"],
    // Fewer than 1% failures across the whole run.
    http_req_failed: ["rate<0.01"],
    redirect_success: ["rate>0.99"],
  },
};

/** Create a pool of short codes before load begins. */
export function setup() {
  const codes = [];
  for (let i = 0; i < 20; i++) {
    const res = http.post(
      `${BASE_URL}/api/shorten`,
      JSON.stringify({ long_url: `https://example.com/target/${i}` }),
      { headers: { "Content-Type": "application/json" } }
    );
    if (res.status === 201) {
      codes.push(res.json("short_code"));
    }
  }
  if (codes.length === 0) {
    throw new Error("setup failed: could not create any short codes");
  }
  return { codes };
}

export default function (data) {
  const code = data.codes[Math.floor(Math.random() * data.codes.length)];

  // redirects: false — we assert on the 301 itself rather than following it
  // out to example.com (which would measure the internet, not our service).
  const res = http.get(`${BASE_URL}/${code}`, { redirects: 0 });

  const ok = check(res, {
    "status is 301": (r) => r.status === 301,
    "location header present": (r) => !!r.headers["Location"],
  });
  redirectSuccess.add(ok);

  const instance = res.headers["X-Instance-Id"];
  if (instance) {
    instancesSeen.add(1, { instance_id: instance });
  }

  sleep(0.1);
}
