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
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture
def running_server(tmp_path):
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, category="idle", amount_usd=14.0)])
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
        assert "$14.00" in body


def test_healthz_returns_ok(running_server):
    with urllib.request.urlopen(f"{running_server}/healthz", timeout=5) as resp:
        assert resp.status == 200
        assert resp.read() == b"ok"


def test_unknown_path_returns_404(running_server):
    with pytest.raises(HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/nope", timeout=5)
    assert exc_info.value.code == 404


def test_server_reflects_current_data_on_each_request(tmp_path):
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, amount_usd=14.0)])
    config = _config(savings_path, tmp_path)

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert "$14.00" in resp.read().decode("utf-8")

        # A new finding lands (e.g. the next detection cycle) -- the next
        # request must reflect it without restarting the server.
        write_estimates(savings_path, [make_estimate(2, amount_usd=99.0)])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
            assert "$14.00" in body
            assert "$99.00" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
