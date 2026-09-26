"""Fetch and parse Prometheus-format metrics from DCGM exporter and
kube-state-metrics.

Both are standard Prometheus text-format exporters, so parsing uses the
official `prometheus_client` parser rather than hand-rolled regex.
"""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import requests
from prometheus_client.parser import text_string_to_metric_families

logger = logging.getLogger(__name__)


class ScrapeError(RuntimeError):
    """Raised when a target could not be scraped after all retries."""


def resolve_targets(url: str) -> list[str]:
    """Expand a metrics URL's hostname into one URL per resolved IP.

    A GPU node's DCGM exporter runs as a DaemonSet -- one pod per node --
    fronted by a single Service name. A normal ClusterIP Service load-
    balances each new connection to exactly one backend pod, so scraping
    the URL as given only ever reaches one node per cycle; over many
    cycles that silently starves every other node of half (or more) of
    its expected samples, without ever surfacing as a scrape failure. A
    headless Service (clusterIP: None) fixes this at the DNS layer
    instead: its name resolves to every backing pod's IP as a separate A
    record. Resolving here and scraping each address individually is what
    actually reaches every node.

    Falls back to the original URL, unchanged, when resolution fails
    (unresolvable host -- e.g. in tests, or a plain non-Kubernetes
    deployment) or resolves to a single address (a non-headless Service,
    or any single-node/single-pod target) -- both already work correctly
    scraped directly, and forcing IP-literal URLs onto them would only
    risk breaking TLS SNI or virtual-hosting setups for no benefit.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        return [url]

    try:
        infos = socket.getaddrinfo(host, parts.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return [url]

    ips = sorted({info[4][0] for info in infos})
    if len(ips) <= 1:
        return [url]

    targets = []
    for ip in ips:
        netloc = f"[{ip}]:{parts.port}" if ":" in ip else f"{ip}:{parts.port}"
        targets.append(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
    return targets


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
    try:
        return parse_metrics(text)
    except Exception as exc:
        # A malformed/unparseable body is a scrape failure just like an
        # unreachable endpoint -- the caller only catches ScrapeError to
        # still record a (failed) scrape_runs row, so a raw parser
        # exception here would skip that entirely and leave zero audit
        # trail for the cycle instead of a recorded failure.
        raise ScrapeError(f"failed to parse metrics from {url}: {exc}") from exc
