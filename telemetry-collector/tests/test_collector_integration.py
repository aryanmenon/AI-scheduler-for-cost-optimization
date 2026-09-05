import requests

from telemetry_collector.collector import run_forever, run_once
from telemetry_collector.config import Config
from telemetry_collector.storage import Storage


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _make_fake_get(dcgm_text, ksm_text, ksm_fails=False):
    def fake_get(url, timeout):
        if "dcgm" in url:
            return _FakeResponse(dcgm_text)
        if "kube-state" in url or "ksm" in url:
            if ksm_fails:
                raise requests.ConnectionError("ksm down")
            return _FakeResponse(ksm_text)
        raise AssertionError(f"unexpected url {url}")
    return fake_get


def _config(tmp_path) -> Config:
    return Config(
        dcgm_exporter_url="http://dcgm-exporter:9400/metrics",
        kube_state_metrics_url="http://kube-state-metrics:8080/metrics",
        sqlite_path=str(tmp_path / "telemetry.db"),
        scrape_interval_seconds=0,
        http_timeout_seconds=1,
        max_scrape_retries=2,
    )


def test_run_once_stores_gpu_metrics(tmp_path, monkeypatch, dcgm_text, ksm_text):
    monkeypatch.setattr(
        "telemetry_collector.metrics_client.requests.get",
        _make_fake_get(dcgm_text, ksm_text),
    )
    config = _config(tmp_path)
    storage = Storage(config.sqlite_path)

    run_id = run_once(config, storage)

    assert run_id == 1
    assert storage.count_gpu_metrics() == 5
    storage.close()


def test_run_once_survives_ksm_failure_but_keeps_dcgm_data(tmp_path, monkeypatch, dcgm_text, ksm_text):
    monkeypatch.setattr(
        "telemetry_collector.metrics_client.requests.get",
        _make_fake_get(dcgm_text, ksm_text, ksm_fails=True),
    )
    config = _config(tmp_path)
    storage = Storage(config.sqlite_path)

    run_once(config, storage)

    assert storage.count_gpu_metrics() == 5
    row = storage._conn.execute("SELECT success, error FROM scrape_runs").fetchone()
    assert row[0] == 1  # DCGM succeeded overall
    assert "kube-state-metrics" in row[1]
    storage.close()


def test_run_once_records_failure_when_dcgm_unreachable(tmp_path, monkeypatch, ksm_text):
    def fake_get(url, timeout):
        raise requests.ConnectionError("dcgm down")

    monkeypatch.setattr("telemetry_collector.metrics_client.requests.get", fake_get)
    monkeypatch.setattr("telemetry_collector.metrics_client.time.sleep", lambda s: None)

    config = _config(tmp_path)
    storage = Storage(config.sqlite_path)

    run_once(config, storage)

    assert storage.count_gpu_metrics() == 0
    row = storage._conn.execute("SELECT success FROM scrape_runs").fetchone()
    assert row[0] == 0
    storage.close()


def test_run_forever_repeats_scrapes_across_cycles(tmp_path, monkeypatch, dcgm_text, ksm_text):
    monkeypatch.setattr(
        "telemetry_collector.metrics_client.requests.get",
        _make_fake_get(dcgm_text, ksm_text),
    )
    config = _config(tmp_path)
    storage = Storage(config.sqlite_path)

    run_forever(config, storage, stop_after=4)

    assert storage.count_scrape_runs() == 4
    assert storage.count_gpu_metrics() == 20
    storage.close()


def test_run_forever_continues_after_unexpected_exception(tmp_path, monkeypatch, dcgm_text, ksm_text):
    calls = {"n": 0}
    real_fake_get = _make_fake_get(dcgm_text, ksm_text)

    def flaky_get(url, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom - simulated unexpected bug")
        return real_fake_get(url, timeout)

    monkeypatch.setattr("telemetry_collector.metrics_client.requests.get", flaky_get)
    config = _config(tmp_path)
    storage = Storage(config.sqlite_path)

    run_forever(config, storage, stop_after=3)

    # First cycle raised before any DB write; the loop must keep going.
    assert storage.count_scrape_runs() == 2
    storage.close()
