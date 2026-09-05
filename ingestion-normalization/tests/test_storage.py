import pytest

from ingestion_normalization.normalizer import normalize_sample
from ingestion_normalization.raw_reader import RawGPUSample
from ingestion_normalization.rollup import compute_rollups
from ingestion_normalization.storage import NormalizedStorage


@pytest.fixture
def storage(tmp_path):
    s = NormalizedStorage(str(tmp_path / "normalized.db"))
    yield s
    s.close()


def _raw(i, scraped_at) -> RawGPUSample:
    return RawGPUSample(
        id=i, scrape_run_id=i, scraped_at=scraped_at, node="gpu-node-1", gpu_index="0",
        gpu_instance_id=None, gpu_uuid="GPU-abc", gpu_model="NVIDIA A100-SXM4-80GB",
        namespace="inference", pod="bert-large-7d4f-xk2p9", container="model-server",
        utilization_pct=50.0, memory_used_mb=1000.0, memory_free_mb=2000.0,
        power_draw_w=200.0, sm_clock_mhz=1000.0,
    )


def test_cursor_defaults_to_zero(storage):
    assert storage.get_cursor() == 0


def test_cursor_roundtrip(storage):
    storage.set_cursor(42)
    assert storage.get_cursor() == 42
    storage.set_cursor(99)
    assert storage.get_cursor() == 99


def test_insert_normalized_samples(storage):
    records = [normalize_sample(_raw(i, i * 30)) for i in range(1, 4)]
    storage.insert_normalized_samples(records)
    assert storage.count_normalized_samples() == 3


def test_insert_is_idempotent_on_replay(storage):
    records = [normalize_sample(_raw(1, 30))]
    storage.insert_normalized_samples(records)
    storage.insert_normalized_samples(records)  # simulate a re-run over the same raw rows
    assert storage.count_normalized_samples() == 1


def test_replace_rollups_is_idempotent_over_overlapping_windows(storage):
    records = [normalize_sample(_raw(i, i * 30)) for i in range(10)]
    storage.insert_normalized_samples(records)
    normalized = [normalize_sample(_raw(i, i * 30)) for i in range(10)]

    rollups_v1 = compute_rollups(normalized[:5], "5m", scrape_interval_seconds=30)
    storage.replace_rollups("5m", 0, 300, rollups_v1)
    assert storage.rollups("5m")[0]["sample_count"] == 5

    rollups_v2 = compute_rollups(normalized, "5m", scrape_interval_seconds=30)
    storage.replace_rollups("5m", 0, 300, rollups_v2)
    all_rollups = storage.rollups("5m")
    assert len(all_rollups) == 1
    assert all_rollups[0]["sample_count"] == 10
