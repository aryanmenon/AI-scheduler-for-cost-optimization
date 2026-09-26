import socket

import pytest
import requests

from telemetry_collector.metrics_client import ScrapeError, fetch_text, parse_metrics, resolve_targets, scrape


def test_parse_metrics_extracts_all_gpu_samples(dcgm_text):
    samples = parse_metrics(dcgm_text)
    util_samples = [s for s in samples if s.name == "DCGM_FI_DEV_GPU_UTIL"]
    assert len(util_samples) == 5  # 2 + 2 + 1 GPUs across three nodes


def test_parse_metrics_preserves_labels(dcgm_text):
    samples = parse_metrics(dcgm_text)
    a100_gpu0 = next(
        s for s in samples
        if s.name == "DCGM_FI_DEV_GPU_UTIL" and s.labels.get("Hostname") == "gpu-node-1" and s.labels.get("gpu") == "0"
    )
    assert a100_gpu0.value == 87
    assert a100_gpu0.labels["namespace"] == "inference"
    assert a100_gpu0.labels["pod"] == "bert-large-7d4f-xk2p9"


def test_parse_metrics_handles_unattributed_gpu(dcgm_text):
    samples = parse_metrics(dcgm_text)
    idle_h100 = next(
        s for s in samples
        if s.name == "DCGM_FI_DEV_GPU_UTIL" and s.labels.get("Hostname") == "gpu-node-2" and s.labels.get("gpu") == "1"
    )
    assert "namespace" not in idle_h100.labels
    assert idle_h100.value == 0


def test_fetch_text_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            pass

        text = "ok"

    def fake_get(url, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.ConnectionError("connection refused")
        return FakeResponse()

    monkeypatch.setattr("telemetry_collector.metrics_client.requests.get", fake_get)
    monkeypatch.setattr("telemetry_collector.metrics_client.time.sleep", lambda s: None)

    result = fetch_text("http://example/metrics", timeout=1, max_retries=3)
    assert result == "ok"
    assert calls["n"] == 2


def test_scrape_raises_scrape_error_on_malformed_body(monkeypatch):
    # Regression: a raw ValueError from the Prometheus parser (as opposed
    # to ScrapeError) would skip run_once's "record a failed scrape_runs
    # row" handling entirely, leaving zero audit trail for that cycle
    # instead of a recorded failure.
    class FakeResponse:
        def raise_for_status(self):
            pass

        text = 'DCGM_FI_DEV_GPU_UTIL{gpu="0"} not_a_number\n'

    monkeypatch.setattr("telemetry_collector.metrics_client.requests.get", lambda url, timeout: FakeResponse())

    with pytest.raises(ScrapeError):
        scrape("http://example/metrics", timeout=1, max_retries=1)


def test_fetch_text_raises_scrape_error_after_exhausting_retries(monkeypatch):
    def fake_get(url, timeout):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr("telemetry_collector.metrics_client.requests.get", fake_get)
    monkeypatch.setattr("telemetry_collector.metrics_client.time.sleep", lambda s: None)

    with pytest.raises(ScrapeError):
        fetch_text("http://example/metrics", timeout=1, max_retries=2)


def test_resolve_targets_expands_headless_service_to_every_pod_ip(monkeypatch):
    # Regression: a DaemonSet's DCGM exporter fronted by a headless Service
    # resolves to one A record per node. Without expanding these, the
    # collector would only ever scrape whichever single address the
    # hostname resolution happened to return first.
    def fake_getaddrinfo(host, port, type=None):
        assert host == "dcgm-exporter"
        assert port == 9400
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 9400)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 9400)),
        ]

    monkeypatch.setattr("telemetry_collector.metrics_client.socket.getaddrinfo", fake_getaddrinfo)

    targets = resolve_targets("http://dcgm-exporter:9400/metrics")
    assert sorted(targets) == [
        "http://10.0.0.1:9400/metrics",
        "http://10.0.0.2:9400/metrics",
    ]


def test_resolve_targets_falls_back_to_original_url_when_unresolvable(monkeypatch):
    # Test environments and plain non-Kubernetes deployments won't have a
    # real DNS entry for the configured hostname -- resolution failing must
    # never break scraping that already worked via the URL as given.
    def fake_getaddrinfo(host, port, type=None):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr("telemetry_collector.metrics_client.socket.getaddrinfo", fake_getaddrinfo)

    targets = resolve_targets("http://dcgm-exporter:9400/metrics")
    assert targets == ["http://dcgm-exporter:9400/metrics"]


def test_resolve_targets_falls_back_when_only_one_address_resolves(monkeypatch):
    # A non-headless (single-IP) Service, or a single-node deployment,
    # already reaches its one real target scraped directly -- no need to
    # rewrite the URL to an IP literal, which could break TLS SNI.
    def fake_getaddrinfo(host, port, type=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 9400))]

    monkeypatch.setattr("telemetry_collector.metrics_client.socket.getaddrinfo", fake_getaddrinfo)

    targets = resolve_targets("http://dcgm-exporter:9400/metrics")
    assert targets == ["http://dcgm-exporter:9400/metrics"]
