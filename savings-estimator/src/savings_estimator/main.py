from __future__ import annotations

import logging
import sys
import time

from savings_estimator.config import Config
from savings_estimator.findings_reader import FindingsReader
from savings_estimator.pipeline import run_once
from savings_estimator.rollup_reader import RollupReader
from savings_estimator.storage import SavingsStorage

logger = logging.getLogger(__name__)


def _write_heartbeat(path: str) -> None:
    try:
        with open(path, "w") as f:
            f.write(str(time.time()))
    except OSError:
        logger.warning("failed to write heartbeat file %s", path)


def run_forever(config: Config, stop_after: int | None = None) -> None:
    storage = SavingsStorage(config.savings_sqlite_path)
    cycles = 0
    while stop_after is None or cycles < stop_after:
        cycle_start = time.monotonic()
        try:
            findings_reader = FindingsReader(config.findings_sqlite_path)
            rollup_reader = RollupReader(config.normalized_sqlite_path)
            try:
                run_once(config, findings_reader, rollup_reader, storage)
            finally:
                findings_reader.close()
                rollup_reader.close()
        except Exception:
            logger.exception("unexpected error during pricing cycle; will retry next interval")
        finally:
            # Written whether or not the cycle above succeeded -- this
            # proves the loop itself is iterating, not that cycles are
            # succeeding (that's what the cycle_complete log's "errors"
            # field is for).
            _write_heartbeat(config.heartbeat_path)

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
        "starting savings-estimator: findings=%s normalized=%s savings=%s poll=%ss",
        config.findings_sqlite_path, config.normalized_sqlite_path,
        config.savings_sqlite_path, config.poll_interval_seconds,
    )
    run_forever(config)


if __name__ == "__main__":
    main()
