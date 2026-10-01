"""Replay real Philly production-cluster telemetry through the real
waste-detector code, to check whether the detectors correctly identify
real waste patterns rather than only the synthetic patterns this project's
own load generators (fragmentation-and-load-test/, heterogeneous-sku-test/)
were designed to produce.

Data: msr-fiddle/philly-traces (Microsoft's real 2017 multi-tenant GPU
training cluster, 552 machines, 117k jobs) -- see README.md in this
directory for how to fetch it and full attribution/citation.
cluster_gpu_util is a real per-minute utilization reading per physical GPU
slot (from nvidia-smi); cluster_job_log attributes each (machine,
gpu-slot, time-window) to a real job (jobid) within a real virtual
cluster (vc), which we map onto this product's (workload, namespace)
concepts.

Window: 2017-10-03 00:00:00 PDT through 2017-11-02 23:59:00 PDT (31 real
days, entirely within one DST regime -- avoids the Nov 5 fall-back
ambiguous-hour edge case). Comfortably covers every detector's minimum
evidence requirement (4h idle/fragmentation streaks, 24h over-provision
window, 7+ distinct calendar days for recurring pattern).

No synthetic data anywhere in this script -- every utilization reading and
every job attribution below is exactly what's in the real trace file.

Usage:
    python3 replay.py /path/to/trace-data
(where /path/to/trace-data contains the extracted cluster_gpu_util and
cluster_job_log files -- see README.md)
"""
from __future__ import annotations

import bisect
import csv
import json
import os
import pickle
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "waste-detector", "src"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "ingestion-normalization", "src"))

from waste_detector.config import Config  # noqa: E402
from waste_detector.rollup_reader import RollupRow  # noqa: E402
from waste_detector.idle import detect_idle  # noqa: E402
from waste_detector.over_provisioning import detect_over_provisioning  # noqa: E402
from waste_detector.fragmentation import detect_fragmentation  # noqa: E402
from waste_detector.patterns import detect_recurring_patterns  # noqa: E402

if len(sys.argv) < 2:
    print("usage: python3 replay.py /path/to/trace-data [output_dir]", file=sys.stderr)
    sys.exit(1)

TRACE_DIR = sys.argv[1]
OUTPUT_DIR = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))
JOB_LOG = os.path.join(TRACE_DIR, "cluster_job_log")
GPU_UTIL = os.path.join(TRACE_DIR, "cluster_gpu_util")

WINDOW_START_STR = "2017-10-03 00:00:00"
WINDOW_END_STR = "2017-11-03 00:00:00"  # exclusive upper bound (31 days)
_TZ_OFFSETS = {"PDT": timedelta(hours=-7), "PST": timedelta(hours=-8)}


def parse_ts(s: str) -> float:
    """'2017-10-03 00:00:00 PDT' -> a real UTC epoch (fixed-offset, not a
    zoneinfo lookup -- this window never crosses the Nov 5 DST boundary,
    and cluster_gpu_util already tells us the offset explicitly per row,
    so a fixed-offset mapping is exact here, not an approximation)."""
    date_part, tz = s.rsplit(" ", 1)
    naive = datetime.strptime(date_part, "%Y-%m-%d %H:%M:%S")
    return (naive - _TZ_OFFSETS[tz]).replace(tzinfo=timezone.utc).timestamp()


def parse_ts_naive(s: str) -> float:
    """job_log's timestamps carry no explicit tz abbreviation -- same
    Pacific wall-clock convention as cluster_gpu_util (both are Philly's
    own internal cluster logs), so treat as PDT within this Oct-only
    window (matches cluster_gpu_util's own PDT tag for the same dates)."""
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return (naive - _TZ_OFFSETS["PDT"]).replace(tzinfo=timezone.utc).timestamp()


WINDOW_START = parse_ts(WINDOW_START_STR + " PDT")
WINDOW_END = parse_ts(WINDOW_END_STR + " PDT")

print(f"[{time.strftime('%H:%M:%S')}] loading job_log ...", flush=True)
with open(JOB_LOG) as f:
    jobs = json.load(f)
print(f"[{time.strftime('%H:%M:%S')}] {len(jobs)} jobs loaded", flush=True)

# (machine_ip, gpu_slot) -> sorted list of (start_ts, end_ts, vc, jobid)
intervals: dict[tuple[str, str], list[tuple[float, float, str, str]]] = defaultdict(list)
skipped_bad_ts = 0
for job in jobs:
    vc = job.get("vc")
    jobid = job.get("jobid")
    for attempt in job.get("attempts") or []:
        st, et = attempt.get("start_time"), attempt.get("end_time")
        if not st:
            continue
        try:
            start_ts = parse_ts_naive(st)
        except Exception:
            skipped_bad_ts += 1
            continue
        if et:
            try:
                end_ts = parse_ts_naive(et)
            except Exception:
                end_ts = WINDOW_END
        else:
            end_ts = WINDOW_END  # still running at snapshot time
        if end_ts < WINDOW_START or start_ts > WINDOW_END:
            continue  # doesn't overlap our replay window at all
        for detail in attempt.get("detail") or []:
            ip = detail.get("ip")
            for gpu in detail.get("gpus") or []:
                intervals[(ip, gpu)].append((start_ts, end_ts, vc, jobid))

for key in intervals:
    intervals[key].sort()
starts_index = {key: [iv[0] for iv in ivs] for key, ivs in intervals.items()}
print(
    f"[{time.strftime('%H:%M:%S')}] built interval index: "
    f"{len(intervals)} (machine,gpu) keys, {sum(len(v) for v in intervals.values())} intervals "
    f"({skipped_bad_ts} attempts skipped for unparseable timestamps)",
    flush=True,
)


def attribute(ip: str, gpu: str, ts: float) -> tuple[str, str] | None:
    key = (ip, gpu)
    starts = starts_index.get(key)
    if not starts:
        return None
    i = bisect.bisect_right(starts, ts) - 1
    if i < 0:
        return None
    start_ts, end_ts, vc, jobid = intervals[key][i]
    if start_ts <= ts < end_ts:
        return (vc, jobid)
    return None


BUCKET_SECONDS = 3600
EXPECTED_PER_HOUR = 60.0  # real Philly cadence: one reading per minute

# (bucket_start, node, gpu_index, namespace, workload) -> [util values]
buckets: dict[tuple, list[float]] = defaultdict(list)

row_count = 0
in_window_count = 0
attributed_count = 0
start_time = time.monotonic()

with open(GPU_UTIL, newline="") as f:
    reader = csv.reader(f)
    header = next(reader)
    for row in reader:
        row_count += 1
        if row_count % 5_000_000 == 0:
            elapsed = time.monotonic() - start_time
            print(
                f"[{time.strftime('%H:%M:%S')}] {row_count/1e6:.1f}M rows read "
                f"({elapsed:.0f}s elapsed, {in_window_count} in-window, {attributed_count} attributed)",
                flush=True,
            )

        ts_str = row[0]
        # Fast reject: lexical string compare on the same fixed-width ISO
        # prefix format, cheaper than a full datetime parse for the ~90%+
        # of rows outside our chosen 31-day window.
        date_part = ts_str[:19]
        if date_part < WINDOW_START_STR or date_part >= WINDOW_END_STR:
            continue

        ts = parse_ts(ts_str)
        machine = row[1]
        in_window_count += 1

        # Row width varies by machine's real GPU count (2, 4, or 8 per
        # cluster_machine_list) plus a trailing empty field from a
        # trailing comma in the source CSV -- not a fixed 8 columns.
        for gpu_idx in range(len(row) - 2):
            val = row[2 + gpu_idx]
            if val == "" or val == "NA":
                continue
            try:
                util = float(val)
            except ValueError:
                continue

            attribution = attribute(machine, f"gpu{gpu_idx}", ts)
            if attribution is None:
                continue  # unattributed capacity -- excluded, same as our real pipeline
            attributed_count += 1
            vc, jobid = attribution

            bucket_start = (int(ts) // BUCKET_SECONDS) * BUCKET_SECONDS
            key = (bucket_start, machine, str(gpu_idx), vc, jobid)
            buckets[key].append(util)

elapsed = time.monotonic() - start_time
print(
    f"[{time.strftime('%H:%M:%S')}] done reading: {row_count} total rows, "
    f"{in_window_count} in-window, {attributed_count} attributed GPU-minute readings, "
    f"{len(buckets)} distinct hourly-bucket groups ({elapsed:.0f}s)",
    flush=True,
)

rollup_rows: list[RollupRow] = []
for i, ((bucket_start, machine, gpu_idx, vc, jobid), values) in enumerate(buckets.items()):
    sample_count = len(values)
    coverage_ratio = min(1.0, sample_count / EXPECTED_PER_HOUR)
    rollup_rows.append(
        RollupRow(
            id=i,
            granularity="hourly",
            bucket_start=float(bucket_start),
            node=machine,
            gpu_index=gpu_idx,
            gpu_instance_id=None,
            namespace=vc,
            workload=jobid,
            sample_count=sample_count,
            expected_sample_count=EXPECTED_PER_HOUR,
            coverage_ratio=coverage_ratio,
            low_confidence=coverage_ratio < 0.5,
            avg_utilization_pct=sum(values) / sample_count,
            max_utilization_pct=max(values),
            avg_memory_used_mb=None,
            avg_power_draw_w=None,
            avg_effective_tflops=None,
        )
    )

print(f"[{time.strftime('%H:%M:%S')}] {len(rollup_rows)} hourly rollup rows built, running detectors ...", flush=True)

# Real pilot defaults (values.yaml), NOT the lowered values-smoke-test.yaml
# thresholds -- the whole point of this replay is to check the detectors
# against the real evidence bar a real pilot customer would be held to.
config = Config(
    normalized_sqlite_path="",
    findings_sqlite_path="",
    poll_interval_seconds=300,
    min_coverage_ratio=0.8,
    idle_threshold_pct=2.0,
    min_idle_streak_hours=4,
    over_provision_threshold_pct=30.0,
    over_provision_min_observation_hours=24,
    fragmentation_threshold_pct=50.0,
    fragmentation_min_underutilized_gpus=2,
    fragmentation_min_streak_hours=4,
    pattern_min_days_observed=7,
    pattern_idle_threshold_pct=5.0,
    pattern_min_consistent_fraction=0.8,
)

idle_findings = detect_idle(rollup_rows, config)
over_provisioned_findings = detect_over_provisioning(rollup_rows, config)
fragmented_findings = detect_fragmentation(rollup_rows, config)
pattern_findings = detect_recurring_patterns(rollup_rows, config)

print()
print("=" * 70)
print("RESULTS: real waste-detector code run against real Philly production data")
print("=" * 70)
print(f"idle findings:            {len(idle_findings)}")
print(f"over-provisioned findings: {len(over_provisioned_findings)}")
print(f"fragmented findings:       {len(fragmented_findings)}")
print(f"recurring-pattern findings:{len(pattern_findings)}")
print()

for name, findings in [
    ("IDLE", idle_findings),
    ("OVER_PROVISIONED", over_provisioned_findings),
    ("FRAGMENTED", fragmented_findings),
    ("RECURRING_PATTERN", pattern_findings),
]:
    print(f"--- {name} (showing up to 5 of {len(findings)}) ---")
    for f_ in findings[:5]:
        print(
            f"  node={f_.node} gpu={f_.gpu_index} ns={f_.namespace} workload={f_.workload} "
            f"confidence={f_.confidence:.2f} metric={f_.metric_value:.2f} :: {f_.detail}"
        )
    print()

os.makedirs(OUTPUT_DIR, exist_ok=True)
out_path = os.path.join(OUTPUT_DIR, "findings.pkl")
with open(out_path, "wb") as f:
    pickle.dump(
        {
            "idle": idle_findings,
            "over_provisioned": over_provisioned_findings,
            "fragmented": fragmented_findings,
            "recurring_pattern": pattern_findings,
            "rollup_row_count": len(rollup_rows),
            "attributed_readings": attributed_count,
            "in_window_readings": in_window_count,
        },
        f,
    )
print(f"[{time.strftime('%H:%M:%S')}] saved raw findings to {out_path}")
