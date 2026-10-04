"""Compare the "before" and "after" runs of the right-sizing mini-test and
say whether the product's right-sizing recommendation held -- or, when the
"before" peak is too high for the product to flag (common for LLM serving:
GPU busy % reads high whenever any request is in flight), whether the sizing
assumption under every recommendation held: busy % moves by the TFLOPS ratio.

  python3 compare.py result-before.json result-after.json

Uses the product's real code (ingestion_normalization.capability and
savings_estimator.ceiling, imported from this repo checkout) to work out
what the product would have recommended from the "before" run, then checks
the "after" run against it with the same pass bars as the client-cluster
kit's verify.py.
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
# Same pass bars as testing/client-cluster-verification-test/verify.py.
P95_PASS, P95_MARGINAL = 1.5, 2.0
MAX_ERROR_RATE = 0.005
MAX_START_LAG_P95_S = 5.0


def ratio(a, b):
    return a / b if a is not None and b else None


def fmt(x, unit="", nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    before, after = (json.load(open(p)) for p in sys.argv[1:3])
    cap_b, cap_a = lookup_capability(before["gpu_name"]), lookup_capability(after["gpu_name"])

    print("== What the product concludes from the 'before' run ==")
    peak = before["util"]["product_peak_median_pct"]
    print(f"before GPU: {before['gpu_name']} -> {cap_b.canonical_name} "
          f"({fmt(cap_b.fp16_tflops, ' TFLOPS', 0)}, {fmt(cap_b.mem_bandwidth_gbps, ' GB/s', 0)})")
    print(f"peak busy % as the product samples it (every 30 s): {peak}% "
          f"(true 1 s max {before['util']['max_1s_pct']}%, mean {before['util']['mean_pct']}%)")
    if not cap_b.known:
        raise SystemExit("before GPU is not in the product's capability table: no recommendation possible")
    flagged = peak <= OVER_PROVISION_THRESHOLD_PCT
    print(f"over-provisioned finding (peak <= {OVER_PROVISION_THRESHOLD_PCT:.0f}%): "
          f"{'YES' if flagged else 'NO -- the product would not recommend a smaller GPU at this load'}")
    rec = right_sized_capability(cap_b.fp16_tflops, peak, SLA_TARGET_PCT)
    print(f"ceiling.py at this peak{'' if flagged else ' (hypothetical)'}: {rec.detail}")

    print("\n== Was the 'after' run comparable? ==")
    if not cap_a.known:
        raise SystemExit(f"after GPU {after['gpu_name']} is not in the capability table")
    same_load = all(before[k] == after[k] for k in ("model", "keep_fraction", "minutes"))
    is_rec = rec.recommended is not None and cap_a.canonical_name == rec.recommended.canonical_name
    print(f"after GPU: {after['gpu_name']} -> {cap_a.canonical_name} "
          f"({'the' if is_rec else 'NOT the'} GPU ceiling.py picks at this peak)")
    print(f"same model, keep fraction and duration: {'yes' if same_load else 'NO -- comparison invalid'}")
    # Every right-sizing number rests on this: busy % moves by the FP16
    # TFLOPS ratio. The alternative for token generation is memory speed.
    tflops_x = cap_b.fp16_tflops / cap_a.fp16_tflops
    bw_x = (cap_b.mem_bandwidth_gbps / cap_a.mem_bandwidth_gbps
            if cap_b.mem_bandwidth_gbps and cap_a.mem_bandwidth_gbps else None)
    predicted_util = before["util"]["mean_pct"] * tflops_x
    print(f"product's model (busy % x {tflops_x:.2f}, the TFLOPS ratio) predicts mean busy "
          f"~{predicted_util:.1f}% on {cap_a.canonical_name}")
    if bw_x:
        print(f"memory-speed model (busy % x {bw_x:.2f}) predicts "
              f"~{min(100.0, before['util']['mean_pct'] * bw_x):.1f}%")

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

    p95_ratio = ratio(la["latency_p95_s"], lb["latency_p95_s"])
    tput_ratio = ratio(la["output_tokens_per_s"], lb["output_tokens_per_s"])
    errors_ok = (la["error_rate"] or 0) <= MAX_ERROR_RATE
    lag_ok = (la["start_lag_p95_s"] or 0) <= MAX_START_LAG_P95_S
    if p95_ratio is None or not errors_ok or not lag_ok:
        verdict = "FAIL"
    elif p95_ratio <= P95_PASS:
        verdict = "PASS"
    elif p95_ratio <= P95_MARGINAL:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    if not same_load:
        verdict += " (INVALID: different load)"

    measured = after["util"]["mean_pct"]
    print("\n== Verdict ==")
    print(f"capacity (did it keep up?): throughput {fmt(tput_ratio, 'x')}, errors "
          f"{'ok' if errors_ok else 'TOO HIGH'}, send lag {'ok' if lag_ok else 'TOO HIGH'}")
    print(f"latency: p95 {fmt(p95_ratio, 'x')} of before (PASS <= {P95_PASS}x, MARGINAL <= {P95_MARGINAL}x)")
    print(f"mean busy %: product's TFLOPS model predicted ~{predicted_util:.1f}%, measured {measured}% "
          f"(peak {after['util']['product_peak_median_pct']}% at 30 s sampling)")
    if bw_x:
        # Which model does the measured busy % ratio sit closer to (in log space)?
        import math
        obs_x = measured / before["util"]["mean_pct"] if before["util"]["mean_pct"] else None
        if obs_x:
            closer = ("TFLOPS (product's assumption holds)"
                      if abs(math.log(obs_x / tflops_x)) <= abs(math.log(obs_x / bw_x))
                      else "memory speed (product's assumption does NOT hold)")
            print(f"busy % moved {obs_x:.2f}x vs TFLOPS {tflops_x:.2f}x / memory speed {bw_x:.2f}x "
                  f"-> closer to {closer}")
    label = ("RIGHT-SIZING RECOMMENDATION" if (flagged and is_rec)
             else "SIZING ASSUMPTION (this load moved to this GPU)")
    print(f"{label}: {verdict}")


if __name__ == "__main__":
    main()
