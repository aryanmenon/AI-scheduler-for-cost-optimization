from __future__ import annotations

import logging
import sys

from telemetry_collector.collector import run_forever
from telemetry_collector.config import Config
from telemetry_collector.storage import Storage


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    config = Config.from_env()
    logging.getLogger(__name__).info(
        "starting telemetry collector: dcgm=%s ksm=%s sqlite=%s interval=%ss",
        config.dcgm_exporter_url,
        config.kube_state_metrics_url,
        config.sqlite_path,
        config.scrape_interval_seconds,
    )
    storage = Storage(config.sqlite_path)
    run_forever(config, storage)


if __name__ == "__main__":
    main()
