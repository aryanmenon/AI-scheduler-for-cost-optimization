"""Compare the "before" and "after" runs of the right-sizing mini-test and
check whether the product's right-sizing promise held on the "after" GPU.

  python3 compare.py result-before.json result-after.json

Uses the product's real code (ingestion_normalization.capability and
savings_estimator.ceiling, imported from this repo checkout).

Since 2026-10-04 ceiling.py sizes on both FP16 TFLOPS and memory bandwidth
and states an expected latency factor F = max(1, compute drop, memory
bandwidth drop). For any "after" GPU the product's promise is therefore:
busy % rises by at most ~F, latency rises by at most ~F, and the GPU still
keeps up (throughput, errors, queueing). This script checks exactly that,
and also reports the fixed 1.5x latency bar from verify.py for reference --
a recommendation can be truthful and still too slow for an interactive
service, which is why the product now says so.

When the "before" peak is above the product's over-provisioned bar (common
for LLM serving: busy % reads high whenever any request is in flight), the
recommendation shown is the one the product would make at that bar, labeled
hypothetical.
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:0] = [os.path.join(REPO, "ingestion-normalization", "src"),
                os.path.join(REPO, "savings-estimator", "src")]

from ingestion_normalization.capability import lookup_capability  # noqa: E402
from savings_estimator.ceiling import right_sized_capability  # noqa: E402

# Product defaults: waste-detector OVER_PROVISION_THRESHOLD_PCT and
# savings-estimator SLA_TARGET_UTILIZATION_PCT.
OVER_PROVISION_THRESHOLD_PCT = 30.0
SLA_TARGET_PCT = 70.0
# Same bars as testing/client-cluster-verification-test/verify.py.
P95_PASS = 1.5
MAX_ERROR_RATE = 0.005
MAX_START_LAG_P95_S = 5.0
MIN_THROUGHPUT_RATIO = 0.9
# Slack on the product's own predicted factor (measurement noise, two hosts).
PREDICTION_TOLERANCE = 1.15


def ratio(a, b):
    return a / b if a is not None and b else None


def fmt(x, unit="", nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    before, after = (json.load(open(p)) for p in sys.argv[1:3])
    cap_b, cap_a = lookup_capability(before["gpu_name"]), lookup_capability(after["gpu_name"])
    if not (cap_b.known and cap_a.known):
        raise SystemExit("both GPUs must be in the product's capability table")

    print("== What the product concludes from the 'before' run ==")
    peak = before["util"]["product_peak_median_pct"]
    print(f"before GPU: {before['gpu_name']} -> {cap_b.canonical_name} "
          f"({cap_b.fp16_tflops:.0f} TFLOPS, {cap_b.mem_bandwidth_gbps:.0f} GB/s)")
    print(f"peak busy % as the product samples it (every 30 s): {peak}% "
          f"(true 1 s max {before['util']['max_1s_pct']}%, mean {before['util']['mean_pct']}%)")
    flagged = peak <= OVER_PROVISION_THRESHOLD_PCT
    print(f"over-provisioned finding (peak <= {OVER_PROVISION_THRESHOLD_PCT:.0f}%): "
          f"{'YES' if flagged else 'NO -- the product would not recommend a smaller GPU at this load'}")
    rec_peak = peak if flagged else OVER_PROVISION_THRESHOLD_PCT
    rec = right_sized_capability(cap_b.fp16_tflops, rec_peak, SLA_TARGET_PCT,
                                 current_mem_bandwidth_gbps=cap_b.mem_bandwidth_gbps)
    print(f"recommendation at {rec_peak:.0f}% peak{'' if flagged else ' (hypothetical: highest peak it would flag)'}: "
          f"{rec.detail}")

    print("\n== The 'after' GPU and the product's stated prediction for it ==")
    same_load = all(before[k] == after[k] for k in ("model", "keep_fraction", "minutes"))
    is_rec = rec.recommended is not None and cap_a.canonical_name == rec.recommended.canonical_name
    print(f"after GPU: {after['gpu_name']} -> {cap_a.canonical_name} "
          f"({'the recommended GPU' if is_rec else 'not the recommended GPU'}); "
          f"same model, keep fraction and duration: {'yes' if same_load else 'NO -- comparison invalid'}")
    tflops_x = cap_b.fp16_tflops / cap_a.fp16_tflops
    bw_x = cap_b.mem_bandwidth_gbps / cap_a.mem_bandwidth_gbps
    factor = max(1.0, tflops_x, bw_x)  # same formula as ceiling.py's expected_latency_factor
    print(f"compute drop {tflops_x:.2f}x, memory bandwidth drop {bw_x:.2f}x -> product predicts busy % "
          f"and latency rise by up to {factor:.2f}x (mean busy ~{before['util']['mean_pct'] * factor:.1f}%)")

    lb, la = before["load"], after["load"]
    print("\n== Measured before vs after ==")
    rows = [
        ("latency p50 (s)", lb["latency_p50_s"], la["latency_p50_s"]),
        ("latency p95 (s)", lb["latency_p95_s"], la["latency_p95_s"]),
        ("latency p99 (s)", lb["latency_p99_s"], la["latency_p99_s"]),
        ("send lag p95 (s)", lb["start_lag_p95_s"], la["start_lag_p95_s"]),
        ("output tokens/s", lb["output_tokens_per_s"], la["output_tokens_per_s"]),
        ("error rate", lb["error_rate"], la["error_rate"]),
        ("busy % mean", before["util"]["mean_pct"], after["util"]["mean_pct"]),
        ("busy % peak (30 s sampling)", peak, after["util"]["product_peak_median_pct"]),
    ]
    print(f"{'metric':<30}{'before':>10}{'after':>10}{'after/before':>14}")
    for name, b, a in rows:
        print(f"{name:<30}{fmt(b):>10}{fmt(a):>10}{fmt(ratio(a, b), 'x'):>14}")

    p95_x = ratio(la["latency_p95_s"], lb["latency_p95_s"])
    busy_x = ratio(after["util"]["mean_pct"], before["util"]["mean_pct"])
    tput_x = ratio(la["output_tokens_per_s"], lb["output_tokens_per_s"])
    limit = factor * PREDICTION_TOLERANCE
    checks = [
        ("kept up: throughput", tput_x is not None and tput_x >= MIN_THROUGHPUT_RATIO,
         f"{fmt(tput_x, 'x')} (>= {MIN_THROUGHPUT_RATIO}x)"),
        ("kept up: errors", (la["error_rate"] or 0) <= MAX_ERROR_RATE, f"{fmt(la['error_rate'])} (<= {MAX_ERROR_RATE})"),
        ("kept up: send lag p95", (la["start_lag_p95_s"] or 0) <= MAX_START_LAG_P95_S,
         f"{fmt(la['start_lag_p95_s'], ' s')} (<= {MAX_START_LAG_P95_S} s)"),
        ("busy % within prediction", busy_x is not None and busy_x <= limit,
         f"{fmt(busy_x, 'x')} (<= {factor:.2f}x +{PREDICTION_TOLERANCE - 1:.0%})"),
        ("latency within stated warning", p95_x is not None and p95_x <= limit,
         f"p95 {fmt(p95_x, 'x')} (<= {factor:.2f}x +{PREDICTION_TOLERANCE - 1:.0%})"),
        ("mean busy % under the SLA target", after["util"]["mean_pct"] <= SLA_TARGET_PCT,
         f"mean {after['util']['mean_pct']}% (<= {SLA_TARGET_PCT:.0f}%)"),
    ]
    print("\n== Did the product's promise hold? ==")
    for name, ok, detail in checks:
        print(f"  [{'ok ' if ok else 'NO '}] {name}: {detail}")
    held = all(ok for _, ok, _ in checks) and same_load
    print(f"  (reference) fixed 1.5x latency bar for an interactive service: p95 {fmt(p95_x, 'x')} -> "
          f"{'within' if p95_x is not None and p95_x <= P95_PASS else 'over'}")
    subject = "RECOMMENDATION" if is_rec else f"PREDICTION FOR {cap_a.canonical_name}"
    print(f"PRODUCT {subject}: {'HELD' if held else 'DID NOT HOLD'}"
          + ("" if same_load else " (INVALID: different load)"))


if __name__ == "__main__":
    main()
