"""Builds a raw telemetry.db fixture using telemetry-collector's own Storage
and correlator, so the raw data ingestion tests consume matches the real
schema exactly (see raw_reader.py's docstring on why production code
doesn't import telemetry_collector, but a dev/test dependency on it here
is the simplest way to avoid schema drift between the two test suites).
"""
import os

import pytest

# telemetry-collector must be installed editable alongside this package for
# these fixtures to work: pip install -e ../telemetry-collector -e .[dev]
from telemetry_collector.correlator import correlate
from telemetry_collector.metrics_client import parse_metrics
from telemetry_collector.storage import Storage as RawStorage

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return f.read()


@pytest.fixture
def dcgm_text() -> str:
    return _read_fixture("dcgm_sample.prom")


@pytest.fixture
def dcgm_mig_text() -> str:
    return _read_fixture("dcgm_sample_mig.prom")


@pytest.fixture
def raw_db_path(tmp_path):
    """A raw telemetry.db with one scrape cycle of the standard fixture."""
    path = str(tmp_path / "telemetry.db")
    storage = RawStorage(path)
    records = correlate(parse_metrics(_read_fixture("dcgm_sample.prom")))
    storage.record_scrape(records, duration_ms=10.0, scraped_at=1_000_000.0)
    storage.close()
    return path


def populate_raw_db(path: str, scrape_texts_with_timestamps: list[tuple[str, float]]) -> None:
    """Write a sequence of scrape cycles (fixture text, scraped_at) into path."""
    storage = RawStorage(path)
    for text, scraped_at in scrape_texts_with_timestamps:
        records = correlate(parse_metrics(text))
        storage.record_scrape(records, duration_ms=10.0, scraped_at=scraped_at)
    storage.close()
