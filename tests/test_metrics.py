def test_metrics_endpoint_exposes_prometheus_format(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    # HELP/TYPE lines are the Prometheus exposition format markers.
    assert "# HELP" in resp.text
    assert "http_requests_total" in resp.text


def test_requests_are_counted(client):
    client.get("/health")
    body = client.get("/metrics").text
    assert 'endpoint="/health"' in body


def test_cache_hit_and_miss_are_recorded(client):
    code = client.post(
        "/api/shorten", json={"long_url": "https://example.com/metrics-test"}
    ).json()["short_code"]

    # First redirect after creation is served from cache (shorten populates it).
    client.get(f"/{code}", follow_redirects=False)
    body = client.get("/metrics").text
    assert "cache_events_total" in body
    assert 'result="hit"' in body


def test_instance_id_header_present(client):
    resp = client.get("/health")
    assert "X-Instance-Id" in resp.headers


def test_endpoint_label_uses_route_template_not_raw_path(client):
    """Guards against unbounded metric cardinality.

    Labeling by raw path would create a separate time series for every short
    code ever visited. The label must be the route template instead.
    """
    code = client.post(
        "/api/shorten", json={"long_url": "https://example.com/cardinality"}
    ).json()["short_code"]
    client.get(f"/{code}", follow_redirects=False)

    body = client.get("/metrics").text
    assert 'endpoint="/{short_code}"' in body
    assert f'endpoint="/{code}"' not in body
