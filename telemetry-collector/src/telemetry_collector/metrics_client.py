"""Fetch and parse Prometheus-format metrics from DCGM exporter and
kube-state-metrics.

Both are standard Prometheus text-format exporters, so parsing uses the
official `prometheus_client` parser rather than hand-rolled regex.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests
from prometheus_client.parser import text_string_to_metric_families

logger = logging.getLogger(__name__)


class ScrapeError(RuntimeError):
    """Raised when a target could not be scraped after all retries."""


@dataclass
class MetricSample:
    name: str
    value: float
    labels: dict = field(default_factory=dict)


def fetch_text(url: str, timeout: float, max_retries: int) -> str:
    """GET a Prometheus /metrics endpoint, retrying transient failures.

    A single flaky scrape must not take down the whole loop -- the caller
    relies on this raising ScrapeError only once retries are exhausted, so
    one bad cycle doesn't lose data for every target.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "scrape attempt %d/%d failed for %s: %s", attempt, max_retries, url, exc
            )
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 10))
    raise ScrapeError(f"failed to scrape {url} after {max_retries} attempts") from last_exc


def parse_metrics(text: str) -> list[MetricSample]:
    """Expand Prometheus text exposition format into flat samples."""
    samples: list[MetricSample] = []
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            samples.append(
                MetricSample(name=sample.name, value=sample.value, labels=dict(sample.labels))
            )
    return samples


def scrape(url: str, timeout: float, max_retries: int) -> list[MetricSample]:
    text = fetch_text(url, timeout=timeout, max_retries=max_retries)
    return parse_metrics(text)
