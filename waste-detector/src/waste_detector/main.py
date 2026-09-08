from __future__ import annotations

import json
import logging
import sys
import time
import urllib.request

from waste_detector.config import Config
from waste_detector.findings import FindingsStorage
from waste_detector.pipeline import run_once
from waste_detector.rollup_reader import RollupReader

logger = logging.getLogger(__name__)


def _write_heartbeat(path: str) -> None:
    try:
        with open(path, "w") as f:
            f.write(str(time.time()))
    except OSError:
        logger.warning("failed to write heartbeat file %s", path)


def _send_alert(webhook_url: str | None, message: str) -> None:
    """Best-effort POST to a Slack-compatible incoming webhook (a plain
    {"text": ...} JSON body). A structured log line only reaches someone
    who's already looking; this is for the case where nobody is. Alerting
    must never be allowed to take down the pipeline it's watching, so any
    failure here is logged and swallowed, never raised.
    """
    if not webhook_url:
        return
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"text": message}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        logger.warning("failed to send alert webhook", exc_info=True)


def run_forever(config: Config, stop_after: int | None = None) -> None:
    storage = FindingsStorage(config.findings_sqlite_path)
    cycles = 0
    consecutive_failures = 0
    while stop_after is None or cycles < stop_after:
        cycle_start = time.monotonic()
        try:
            reader = RollupReader(config.normalized_sqlite_path)
            try:
                run_once(config, reader, storage)
            finally:
                reader.close()
        except Exception:
            logger.exception("unexpected error during detection cycle; will retry next interval")
            consecutive_failures += 1
            # Edge-triggered, not level-triggered: fires once on crossing
            # the threshold, not on every cycle after -- a structured log
            # line already exists per cycle for anyone polling; this is
            # for getting a human's attention once, not paging them every
            # interval for the same ongoing problem.
            if consecutive_failures == config.alert_consecutive_failure_threshold:
                _send_alert(
                    config.alert_webhook_url,
                    f"[gpu-cost-optimizer] waste-detector: "
                    f"{consecutive_failures} consecutive failed cycles -- investigate.",
                )
        else:
            if consecutive_failures >= config.alert_consecutive_failure_threshold:
                _send_alert(
                    config.alert_webhook_url,
                    f"[gpu-cost-optimizer] waste-detector: "
                    f"recovered after {consecutive_failures} consecutive failed cycles.",
                )
            consecutive_failures = 0
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
        "starting waste-detector: normalized=%s findings=%s poll=%ss",
        config.normalized_sqlite_path, config.findings_sqlite_path, config.poll_interval_seconds,
    )
    run_forever(config)


if __name__ == "__main__":
    main()
