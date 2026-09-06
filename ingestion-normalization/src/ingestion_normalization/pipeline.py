"""Wire raw_reader -> normalizer -> rollup -> storage into one ingestion cycle.

Each cycle: read raw samples newer than the stored cursor, normalize them,
persist them, then recompute rollups (at all three granularities) for
whatever time range those new samples touched. Recomputing rather than
incrementally updating rollups keeps the arithmetic simple and correct --
see NormalizedStorage.replace_rollups for why that's safe to do repeatedly.
"""
from __future__ import annotations

import logging
import time

from ingestion_normalization.config import Config
from ingestion_normalization.normalizer import NormalizedRecord, normalize_samples
from ingestion_normalization.raw_reader import RawReader
from ingestion_normalization.rollup import GRANULARITY_SECONDS, bucket_start_for, compute_rollups
from ingestion_normalization.storage import NormalizedStorage

logger = logging.getLogger(__name__)


def _row_to_normalized_record(row) -> NormalizedRecord:
    return NormalizedRecord(
        scrape_run_id=row["scrape_run_id"],
        scraped_at=row["scraped_at"],
        node=row["node"],
        gpu_index=row["gpu_index"],
        gpu_instance_id=row["gpu_instance_id"],
        gpu_uuid=row["gpu_uuid"],
        gpu_model=row["gpu_model"],
        namespace=row["namespace"],
        workload=row["workload"],
        pod=row["pod"],
        container=row["container"],
        utilization_pct=row["utilization_pct"],
        memory_used_mb=row["memory_used_mb"],
        memory_free_mb=row["memory_free_mb"],
        power_draw_w=row["power_draw_w"],
        capability_known=bool(row["capability_known"]),
        fp16_tflops=row["fp16_tflops"],
        effective_tflops=row["effective_tflops"],
    )


def run_once(config: Config, reader: RawReader, storage: NormalizedStorage) -> int:
    """Run a single ingestion cycle. Returns the number of samples ingested."""
    cursor = storage.get_cursor()
    raw_samples = reader.fetch_since(cursor)

    if not raw_samples:
        logger.info("no new raw samples since run_id=%d", cursor)
        return 0

    normalized = normalize_samples(raw_samples)
    storage.insert_normalized_samples(normalized)

    new_cursor = max(s.scrape_run_id for s in raw_samples)
    storage.set_cursor(new_cursor)

    min_ts = min(r.scraped_at for r in normalized)
    max_ts = max(r.scraped_at for r in normalized)
    _recompute_touched_rollups(config, storage, min_ts, max_ts)
    _prune(config, storage)

    logger.info(
        "ingested %d samples (cursor %d -> %d), recomputed rollups for [%.0f, %.0f]",
        len(normalized), cursor, new_cursor, min_ts, max_ts,
    )
    return len(normalized)


def _prune(config: Config, storage: NormalizedStorage, now: float | None = None) -> None:
    now = now if now is not None else time.time()

    if config.normalized_samples_retention_hours > 0:
        cutoff = now - config.normalized_samples_retention_hours * 3600
        deleted = storage.prune_normalized_samples_older_than(cutoff)
        if deleted:
            logger.info(
                "pruned %d normalized_samples rows older than %.1fh",
                deleted, config.normalized_samples_retention_hours,
            )

    if config.rollups_retention_hours > 0:
        cutoff = now - config.rollups_retention_hours * 3600
        deleted = storage.prune_rollups_older_than(cutoff)
        if deleted:
            logger.info(
                "pruned %d rollups rows older than %.1fh", deleted, config.rollups_retention_hours
            )


def _daily_recompute_due(config: Config, storage: NormalizedStorage, now: float) -> bool:
    interval = config.daily_rollup_min_recompute_interval_seconds
    if interval <= 0:
        return True
    last = storage.get_last_rollup_recompute_at("daily")
    return last is None or (now - last) >= interval


def _recompute_touched_rollups(
    config: Config, storage: NormalizedStorage, min_ts: float, max_ts: float, now: float | None = None
) -> None:
    now = now if now is not None else time.time()

    for granularity, bucket_seconds in GRANULARITY_SECONDS.items():
        if granularity == "daily" and not _daily_recompute_due(config, storage, now):
            continue

        window_start = bucket_start_for(min_ts, bucket_seconds)
        window_end = bucket_start_for(max_ts, bucket_seconds) + bucket_seconds

        rows = storage.normalized_samples_between(window_start, window_end)
        records = [_row_to_normalized_record(r) for r in rows]

        rollups = compute_rollups(
            records,
            granularity,
            scrape_interval_seconds=config.source_scrape_interval_seconds,
            low_confidence_threshold=config.low_confidence_coverage_threshold,
        )
        storage.replace_rollups(granularity, window_start, window_end, rollups)

        if granularity == "daily":
            storage.set_last_rollup_recompute_at("daily", now)
