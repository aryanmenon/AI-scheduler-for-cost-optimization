"""Bursty load generator for the fragmentation/realistic-traffic test.

Drives one or more inference endpoints with alternating burst/quiet
periods, each randomized within a range rather than fixed -- a perfectly
periodic script is still a pattern you already know the shape of; adding
jitter is a small step toward traffic that isn't trivially predictable.

Run one process against both workloads at once (they're driven on
independent threads with independent random schedules, so they don't
happen to burst in lockstep):

    python load_generator.py \\
        --target a=http://localhost:8001/generate \\
        --target b=http://localhost:8002/generate \\
        --duration-hours 24

Point --target at wherever you've exposed each workload's Service --
a `kubectl port-forward` per workload is the simplest option from outside
the cluster.
"""
from __future__ import annotations

import argparse
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


def _fire(session: requests.Session, url: str, max_new_tokens: int) -> bool:
    try:
        resp = session.post(
            url, json={"prompt": "The quick brown fox", "max_new_tokens": max_new_tokens}, timeout=30
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def drive(
    name: str,
    url: str,
    end_at: float,
    burst_range: tuple[float, float],
    quiet_range: tuple[float, float],
    concurrency: int,
    max_new_tokens: int,
) -> None:
    session = requests.Session()
    cycle = 0
    while time.monotonic() < end_at:
        cycle += 1
        burst_s = random.uniform(*burst_range)
        quiet_s = random.uniform(*quiet_range)
        burst_end = min(time.monotonic() + burst_s, end_at)

        log(f"{name}: cycle {cycle} -- bursting for {burst_s:.0f}s at concurrency {concurrency}")
        sent = ok = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while time.monotonic() < burst_end:
                futures = [pool.submit(_fire, session, url, max_new_tokens) for _ in range(concurrency)]
                for f in futures:
                    sent += 1
                    ok += 1 if f.result() else 0

        remaining = end_at - time.monotonic()
        if remaining <= 0:
            break
        log(f"{name}: cycle {cycle} done -- {ok}/{sent} requests ok, quiet for {quiet_s:.0f}s")
        time.sleep(min(quiet_s, remaining))

    log(f"{name}: duration elapsed, stopping")


def _parse_target(value: str) -> tuple[str, str]:
    name, _, url = value.partition("=")
    if not name or not url:
        raise argparse.ArgumentTypeError(f"expected name=url, got {value!r}")
    return name, url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=_parse_target, action="append", required=True,
                         help="name=url, repeatable -- one per workload")
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--burst-seconds-min", type=float, default=60.0)
    parser.add_argument("--burst-seconds-max", type=float, default=300.0)
    parser.add_argument("--quiet-seconds-min", type=float, default=300.0)
    parser.add_argument("--quiet-seconds-max", type=float, default=1800.0)
    parser.add_argument("--concurrency", type=int, default=4,
                         help="parallel in-flight requests during a burst")
    parser.add_argument("--max-new-tokens", type=int, default=64,
                         help="higher = more GPU work per request")
    args = parser.parse_args()

    end_at = time.monotonic() + args.duration_hours * 3600
    log(f"starting {len(args.target)} target(s) for {args.duration_hours:.1f}h "
        f"(burst {args.burst_seconds_min:.0f}-{args.burst_seconds_max:.0f}s, "
        f"quiet {args.quiet_seconds_min:.0f}-{args.quiet_seconds_max:.0f}s)")

    threads = [
        threading.Thread(
            target=drive,
            args=(name, url, end_at,
                  (args.burst_seconds_min, args.burst_seconds_max),
                  (args.quiet_seconds_min, args.quiet_seconds_max),
                  args.concurrency, args.max_new_tokens),
            daemon=True,
        )
        for name, url in args.target
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log("all targets finished")


if __name__ == "__main__":
    main()
