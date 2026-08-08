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


def test_rate_limit_returns_429(client, monkeypatch):
    """Requests past the configured limit are rejected with 429.

    The limit is set explicitly here rather than relying on the default: a
    developer with a local .env (which pydantic-settings loads automatically)
    would otherwise inherit their own value and see this test fail for reasons
    that have nothing to do with the code.
    """
    from app import rate_limiter

    monkeypatch.setattr(rate_limiter.settings, "rate_limit_requests", 5)

    statuses = [
        client.post("/api/shorten", json={"long_url": "https://example.com"}).status_code
        for _ in range(8)
    ]

    assert statuses[:5] == [201] * 5, "first 5 should be allowed"
    assert statuses[5:] == [429] * 3, "requests past the limit should be rejected"
