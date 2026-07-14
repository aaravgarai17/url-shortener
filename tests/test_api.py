def test_shorten_returns_code(client):
    resp = client.post("/api/shorten", json={"long_url": "https://example.com/page"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["short_code"]
    assert body["long_url"] == "https://example.com/page"
    assert body["short_url"].endswith(body["short_code"])


def test_redirect_resolves_to_long_url(client):
    code = client.post(
        "/api/shorten", json={"long_url": "https://example.com/target"}
    ).json()["short_code"]

    resp = client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "https://example.com/target"


def test_unique_codes_for_different_urls(client):
    a = client.post("/api/shorten", json={"long_url": "https://a.com"}).json()
    b = client.post("/api/shorten", json={"long_url": "https://b.com"}).json()
    assert a["short_code"] != b["short_code"]


def test_stats_track_clicks(client):
    code = client.post(
        "/api/shorten", json={"long_url": "https://example.com/x"}
    ).json()["short_code"]

    for _ in range(3):
        client.get(f"/{code}", follow_redirects=False)

    stats = client.get(f"/api/stats/{code}").json()
    assert stats["click_count"] == 3


def test_missing_code_returns_404(client):
    assert client.get("/doesnotexist", follow_redirects=False).status_code == 404


def test_invalid_url_rejected(client):
    assert client.post("/api/shorten", json={"long_url": "not-a-url"}).status_code == 422


def test_rate_limit_returns_429(client):
    # Default limit is 20/min in tests; the 21st request should be rejected.
    last = None
    for _ in range(25):
        last = client.post("/api/shorten", json={"long_url": "https://example.com"})
    assert last.status_code == 429
