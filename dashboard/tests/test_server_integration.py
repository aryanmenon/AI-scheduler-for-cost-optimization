import json
import threading
import urllib.request
from urllib.error import HTTPError

import pytest
from conftest import make_estimate, write_estimates

from dashboard.config import Config
from dashboard.server import build_server


def _config(savings_path: str, tmp_path, **overrides) -> Config:
    defaults = dict(
        savings_sqlite_path=savings_path,
        report_output_path=str(tmp_path / "report.html"),
        server_host="127.0.0.1",
        server_port=0,  # ephemeral: OS assigns a free port
        top_findings_limit=25,
        rate_limit_max_requests=0,  # unlimited by default; opted into per-test below
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture
def running_server(tmp_path):
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, category="idle", amount_inr=14.0)])
    config = _config(savings_path, tmp_path)

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_root_serves_html_report(running_server):
    with urllib.request.urlopen(f"{running_server}/", timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        body = resp.read().decode("utf-8")
        assert "<!doctype html>" in body
        assert "₹14.00" in body


def test_healthz_returns_ok(running_server):
    with urllib.request.urlopen(f"{running_server}/healthz", timeout=5) as resp:
        assert resp.status == 200
        assert resp.read() == b"ok"


def test_unknown_path_returns_404(running_server):
    with pytest.raises(HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/nope", timeout=5)
    assert exc_info.value.code == 404


def test_root_requires_auth_token_when_configured(tmp_path):
    # Regression: the server used to serve the report to anyone who could
    # reach the port, with no way to require a shared secret.
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, category="idle", amount_inr=14.0)])
    config = _config(savings_path, tmp_path, auth_token="s3cret")

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/"

        with pytest.raises(HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=5)
        assert exc_info.value.code == 401

        req = urllib.request.Request(url, headers={"Authorization": "Bearer s3cret"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200

        req = urllib.request.Request(url, headers={"Authorization": "Bearer wrong"})
        with pytest.raises(HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=5)
        assert exc_info.value.code == 401
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_healthz_does_not_require_auth_token(tmp_path):
    # A liveness/readiness probe must keep working without a token.
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, amount_inr=14.0)])
    config = _config(savings_path, tmp_path, auth_token="s3cret")

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
            assert resp.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_root_rate_limits_repeated_requests_from_same_client(tmp_path):
    # Regression: ThreadingHTTPServer has no built-in connection/thread
    # cap, and every request re-reads the DB and re-renders -- an
    # unthrottled client could drive unbounded CPU/thread use.
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, amount_inr=14.0)])
    config = _config(savings_path, tmp_path, rate_limit_max_requests=2, rate_limit_window_seconds=60.0)

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/"

        for _ in range(2):
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert resp.status == 200

        with pytest.raises(HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=5)
        assert exc_info.value.code == 429
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_server_reflects_current_data_on_each_request(tmp_path):
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, amount_inr=14.0)])
    config = _config(savings_path, tmp_path)

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert "₹14.00" in resp.read().decode("utf-8")

        # A new finding lands (e.g. the next detection cycle) -- the next
        # request must reflect it without restarting the server.
        write_estimates(savings_path, [make_estimate(2, amount_inr=99.0)])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
            assert "₹14.00" in body
            assert "₹99.00" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_server_alerts_after_consecutive_report_failures_then_on_recovery(tmp_path, monkeypatch):
    # Regression: a structured cycle_complete log line only reaches an
    # operator who's already looking for it. Once report-generation
    # failures cross the configured threshold, a human-visible webhook
    # alert must fire -- and exactly once (edge-triggered), not on every
    # request past it. A second alert must fire once it recovers.
    posted = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import dashboard.server as server_module

    real_urlopen = server_module.urllib.request.urlopen
    webhook_url = "https://hooks.example.test/webhook"

    def fake_urlopen(req, timeout=None):
        if isinstance(req, urllib.request.Request) and req.full_url == webhook_url:
            posted.append(json.loads(req.data.decode("utf-8"))["text"])
            return _FakeResponse()
        return real_urlopen(req, timeout=timeout)

    monkeypatch.setattr(server_module.urllib.request, "urlopen", fake_urlopen)

    # savings.db doesn't exist yet -- ReportReader opens it mode=ro, so
    # every request fails until it's created below.
    savings_path = str(tmp_path / "savings.db")
    config = _config(
        savings_path, tmp_path,
        alert_webhook_url=webhook_url,
        alert_consecutive_failure_threshold=3,
    )

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/"

        for _ in range(4):
            with pytest.raises(HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)
            assert exc_info.value.code == 500

        # 3rd failure crosses the threshold (one alert); the 4th stays
        # failed past it (no new alert).
        assert len(posted) == 1
        assert "3 consecutive failed" in posted[0]

        write_estimates(savings_path, [make_estimate(1, amount_inr=14.0)])
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200

        assert len(posted) == 2
        assert "recovered" in posted[1]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
