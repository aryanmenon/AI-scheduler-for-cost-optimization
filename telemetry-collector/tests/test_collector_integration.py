import json
import os

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
        heartbeat_path=str(tmp_path / "heartbeat"),
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


def test_run_once_emits_structured_cycle_complete_log(tmp_path, monkeypatch, dcgm_text, ksm_text, caplog):
    # Regression: an operator needs a consistent, parseable signal per
    # cycle without reading source code to learn what each service's
    # ad-hoc log message means. This is the schema shared across all five
    # services: event/component/duration_ms/rows_in/rows_out/errors.
    monkeypatch.setattr(
        "telemetry_collector.metrics_client.requests.get",
        _make_fake_get(dcgm_text, ksm_text),
    )
    config = _config(tmp_path)
    storage = Storage(config.sqlite_path)

    with caplog.at_level("INFO", logger="telemetry_collector.collector"):
        run_once(config, storage)

    payloads = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    cycle_logs = [p for p in payloads if p.get("event") == "cycle_complete"]
    assert len(cycle_logs) == 1
    log = cycle_logs[0]
    assert log["component"] == "telemetry-collector"
    assert log["rows_in"] > 0  # raw DCGM metric samples scraped, pre-correlation
    assert log["rows_out"] == 5  # 5 GPUs, post-correlation
    assert log["errors"] == 0
    assert isinstance(log["duration_ms"], (int, float))
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


def test_run_once_records_failed_run_on_malformed_dcgm_body(tmp_path, monkeypatch, ksm_text):
    # Regression: a malformed DCGM body used to raise a plain ValueError
    # out of run_once entirely (only ScrapeError was caught), leaving zero
    # rows in scrape_runs for that cycle -- an invisible gap in the audit
    # trail. It must now be recorded as a failed run, like any other
    # scrape failure.
    monkeypatch.setattr(
        "telemetry_collector.metrics_client.requests.get",
        _make_fake_get('DCGM_FI_DEV_GPU_UTIL{gpu="0"} not_a_number\n', ksm_text),
    )
    config = _config(tmp_path)
    storage = Storage(config.sqlite_path)

    run_once(config, storage)

    assert storage.count_scrape_runs() == 1
    row = storage._conn.execute("SELECT success, error FROM scrape_runs").fetchone()
    assert row[0] == 0
    assert "parse" in row[1]
    storage.close()


def test_run_once_prunes_old_scrapes_per_retention_config(tmp_path, monkeypatch, dcgm_text, ksm_text):
    # Regression: without pruning, this unattended-for-weeks database grows
    # without bound. A short retention window must actually get enforced
    # by run_once, not just exist as an unused config knob.
    monkeypatch.setattr(
        "telemetry_collector.metrics_client.requests.get",
        _make_fake_get(dcgm_text, ksm_text),
    )
    config = Config(
        dcgm_exporter_url="http://dcgm-exporter:9400/metrics",
        kube_state_metrics_url="http://kube-state-metrics:8080/metrics",
        sqlite_path=str(tmp_path / "telemetry.db"),
        scrape_interval_seconds=0,
        http_timeout_seconds=1,
        max_scrape_retries=2,
        retention_hours=1.0,
    )
    storage = Storage(config.sqlite_path)
    storage.record_scrape([], duration_ms=1.0, success=True, scraped_at=1000.0)  # ancient, pre-existing

    run_once(config, storage)  # a fresh, "now" scrape

    assert storage.count_scrape_runs() == 1  # the ancient run was pruned; the fresh one wasn't
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


def test_run_forever_writes_heartbeat_every_cycle_even_after_exception(
    tmp_path, monkeypatch, dcgm_text, ksm_text
):
    # Regression: run_once's own exceptions are caught inside run_forever
    # (see test above), so the process never crashes on a bad cycle -- a
    # plain "is the process alive" Kubernetes liveness check can't detect
    # a genuinely stuck loop. The heartbeat file must be touched on every
    # iteration regardless of whether that cycle's scrape succeeded, so an
    # exec probe checking its mtime actually reflects loop liveness.
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

    run_forever(config, storage, stop_after=1)

    # The very first (and only) cycle raised, yet the heartbeat must still
    # have been written -- it reflects loop liveness, not cycle success.
    assert os.path.exists(config.heartbeat_path)
    first_heartbeat = float(open(config.heartbeat_path).read())

    run_forever(config, storage, stop_after=2)
    second_heartbeat = float(open(config.heartbeat_path).read())

    assert second_heartbeat > first_heartbeat
    storage.close()
