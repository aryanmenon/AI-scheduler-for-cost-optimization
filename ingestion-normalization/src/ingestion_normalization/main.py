from __future__ import annotations

import logging
import sys
import time

from ingestion_normalization.config import Config
from ingestion_normalization.pipeline import run_once
from ingestion_normalization.raw_reader import RawReader
from ingestion_normalization.storage import NormalizedStorage

logger = logging.getLogger(__name__)


def run_forever(config: Config, stop_after: int | None = None) -> None:
    storage = NormalizedStorage(config.normalized_sqlite_path)
    cycles = 0
    while stop_after is None or cycles < stop_after:
        cycle_start = time.monotonic()
        try:
            reader = RawReader(config.raw_sqlite_path)
            try:
                run_once(config, reader, storage)
            finally:
                reader.close()
        except Exception:
            logger.exception("unexpected error during ingestion cycle; will retry next interval")

        cycles += 1
        if stop_after is not None and cycles >= stop_after:
            break

        elapsed = time.monotonic() - cycle_start
        time.sleep(max(0.0, config.poll_interval_seconds - elapsed))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    config = Config.from_env()
    logging.getLogger(__name__).info(
        "starting ingestion-normalization: raw=%s normalized=%s poll=%ss",
        config.raw_sqlite_path, config.normalized_sqlite_path, config.poll_interval_seconds,
    )
    run_forever(config)


if __name__ == "__main__":
    main()
