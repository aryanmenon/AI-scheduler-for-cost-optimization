"""Compare what the product predicted with what was actually measured.

Reads one results directory (see README) and prints a Markdown report:
  1. which findings fired, per workload, against what the setup should cause;
  2. how closely the product's measured utilization matches an independent
     nvidia-smi log (if nvsmi.csv is present);
  3. whether each ₹ estimate follows from its own inputs and the configured
     rates (arithmetic check);
  4. ground truth: the product's claims vs the measured before/after runs
     (idle and no-pod hours, right-sizing, co-location, fewer GPUs).

Expected files in the results directory (missing ones are reported as
"not run", not errors):
  product.json            dump_product_data.py output
  rates.json              rates.py output (real rental prices)
  load-main.log, load-side.log            phase-1 load job logs
  coloc-main.log, coloc-side.log          co-location run logs
  phase2-main.log         the same load on the recommended GPU
  train-2gpu.log          phase-1 training job log
  train-1gpu-w2.log, train-1gpu-w4.log    fewer-GPU runs
  nvsmi.csv               nvidia-smi --query-gpu=timestamp,index,utilization.gpu ... -l 60

Usage: python3 verify.py results/<tag> > results/<tag>/REPORT.md
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

HOURS_PER_MONTH = 730.0  # savings-estimator default
EXPECTED = {
    "vllm-main": {"over_provisioned", "fragmented"},
    "vllm-side": {"over_provisioned", "fragmented"},
    "train-2gpu": {"multi_gpu_oversized", "idle"},
}
# Pass criteria for a recommendation's "after" run vs its "before" run.
P95_PASS, P95_MARGINAL = 1.5, 2.0
MAX_ERROR_RATE = 0.005
MAX_START_LAG_P95_S = 5.0


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def tagged_lines(path, tag):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, errors="replace") as f:
        for line in f:
            idx = line.find(tag + " ")
            if idx >= 0:
                try:
                    out.append(json.loads(line[idx + len(tag) + 1:]))
                except ValueError:
                    pass
    return out


def summary(path):
    lines = tagged_lines(path, "SUMMARY_JSON")
    return lines[-1] if lines else None


def train_summary(path):
    lines = tagged_lines(path, "TRAIN_SUMMARY_JSON")
    return lines[-1] if lines else None


def phases(path):
    return {p["phase"]: p["t"] for p in tagged_lines(path, "PHASE_JSON")}


def fmt(x, nd=1, unit=""):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:,.{nd}f}{unit}"
    return f"{x}{unit}"


def inr(x):
    return "n/a" if x is None else f"₹{x:,.0f}"


def workload_of(name):
    if not name:
        return "(no pod)"
    for key in EXPECTED:
        if key in name:
            return key
    return name


def section_findings(product):
    print("## 1. Findings fired vs expected\n")
    fired = defaultdict(lambda: defaultdict(int))
    for f in product.get("findings", []):
        fired[workload_of(f.get("workload"))][f["category"]] += 1
    print("| Workload | Expected | Fired (count) | Missing |")
    print("|---|---|---|---|")
    for wl in sorted(set(EXPECTED) | set(fired)):
        exp = EXPECTED.get(wl, set())
        got = fired.get(wl, {})
        fired_txt = ", ".join(f"{c} ({n})" for c, n in sorted(got.items())) or "none"
        missing = ", ".join(sorted(exp - set(got))) or "-"
        print(f"| {wl} | {', '.join(sorted(exp)) or '(none expected)'} | {fired_txt} | {missing} |")
    print("\n`(no pod)` should show `unattributed_gpu_time` after the training job exits.\n")


def section_fidelity(product, results_dir):
    print("## 2. Utilization fidelity: product vs independent nvidia-smi\n")
    path = os.path.join(results_dir, "nvsmi.csv")
    if not os.path.exists(path):
        print("nvsmi.csv not present -- not run.\n")
        return
    smi = defaultdict(list)
    with open(path) as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        i_ts = next(i for i, h in enumerate(header) if h.startswith("timestamp"))
        i_idx = next(i for i, h in enumerate(header) if h.startswith("index"))
        i_util = next(i for i, h in enumerate(header) if h.startswith("utilization.gpu"))
        for row in reader:
            try:
                ts = datetime.strptime(row[i_ts].strip(), "%Y/%m/%d %H:%M:%S.%f").timestamp()
                util = float(row[i_util].strip().split()[0])
            except (ValueError, IndexError):
                continue
            smi[(row[i_idx].strip(), int(ts // 3600) * 3600)].append(util)
    prod = defaultdict(list)
    for r in product.get("hourly_rollups", []):
        if r.get("avg_utilization_pct") is not None and r.get("coverage_ratio", 0) >= 0.8:
            prod[(str(r["gpu_index"]), int(r["bucket_start"]))].append(r["avg_utilization_pct"])
    diffs = []
    for key, vals in prod.items():
        if key in smi and len(smi[key]) >= 30:  # at least half an hour of 1-min samples
            diffs.append(abs(sum(vals) / len(vals) - sum(smi[key]) / len(smi[key])))
    if not diffs:
        print("No overlapping GPU-hours between the two logs (check nvidia-smi was started with "
              "`-l 60` and that the host clock is UTC).\n")
        return
    diffs.sort()
    print(f"{len(diffs)} GPU-hours compared. Absolute difference in hourly average utilization: "
          f"mean {sum(diffs) / len(diffs):.1f} pts, median {diffs[len(diffs) // 2]:.1f} pts, "
          f"max {diffs[-1]:.1f} pts. (nvidia-smi samples once a minute and the product every scrape "
          f"interval, so a few points of difference is expected; double digits is a problem.)\n")


def rate_for(name, rates):
    if not rates:
        return None
    return rates.get("inr_per_gpu_hour", {}).get(name)


def section_arithmetic(product, rates):
    print("## 3. ₹ arithmetic: does each estimate follow from its own inputs?\n")
    findings = {f["id"]: f for f in product.get("findings", [])}
    phase1_rate = rate_for(rates.get("phase1_gpu"), rates) if rates else None
    checked = mismatched = skipped = 0
    rows = []
    for e in product.get("estimates", []):
        if not e.get("priceable") or e.get("amount_inr") is None:
            continue
        f = findings.get(e["finding_id"])
        if f is None or phase1_rate is None:
            skipped += 1
            continue
        hours = (f["window_end"] - f["window_start"]) / 3600.0
        cat, mv = f["category"], f["metric_value"]
        expected = None
        if cat == "idle":
            expected = phase1_rate * hours
        elif cat in ("underutilized", "unattributed_gpu_time"):
            expected = phase1_rate * mv * hours
        elif cat == "multi_gpu_oversized":
            expected = phase1_rate * mv * 0.5 * HOURS_PER_MONTH
        elif cat == "over_provisioned":
            m = re.search(r"right-size to (.+?)(?: \(|$)", e.get("recommended_action", ""))
            rec_rate = rate_for(m.group(1).strip(), rates) if m else None
            if m and rec_rate is not None:
                expected = max(0.0, (phase1_rate - rec_rate) * HOURS_PER_MONTH)
        if expected is None:
            skipped += 1
            continue
        checked += 1
        ok = abs(expected - e["amount_inr"]) <= max(1.0, 0.01 * expected)
        if not ok:
            mismatched += 1
            rows.append(f"| {e['id']} | {cat} | {inr(e['amount_inr'])} | {inr(expected)} |")
    print(f"{checked} estimates recomputed from their findings and rates.json; {mismatched} mismatched; "
          f"{skipped} not recomputable here (fragmentation needs rollup averages; over-provisioned needs "
          f"a rate for the recommended GPU in rates.json).\n")
    if rows:
        print("| Estimate | Category | Product | Recomputed |\n|---|---|---|---|")
        print("\n".join(rows) + "\n")


def compare_runs(before, after):
    if not before or not after:
        return None, "not run"
    ratio = (after["latency_p95_s"] / before["latency_p95_s"]) if before.get("latency_p95_s") else None
    err = after.get("error_rate") or 0.0
    lag = after.get("start_lag_p95_s") or 0.0
    if err > max(MAX_ERROR_RATE, before.get("error_rate") or 0.0) or lag > MAX_START_LAG_P95_S:
        verdict = "FAIL"
    elif ratio is not None and ratio <= P95_PASS:
        verdict = "PASS"
    elif ratio is not None and ratio <= P95_MARGINAL:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    return ratio, verdict


def run_table(pairs):
    print("| Run | Requests | Error rate | p50 latency | p95 latency | p95 send lag | Output tok/s |")
    print("|---|---|---|---|---|---|---|")
    for name, s in pairs:
        if not s:
            print(f"| {name} | not run | | | | | |")
            continue
        print(f"| {name} | {s['requests']:,} | {fmt((s.get('error_rate') or 0) * 100, 2, '%')} | "
              f"{fmt(s.get('latency_p50_s'), 2, 's')} | {fmt(s.get('latency_p95_s'), 2, 's')} | "
              f"{fmt(s.get('start_lag_p95_s'), 2, 's')} | {fmt(s.get('output_tokens_per_s'), 0)} |")
    print()


def estimates_for(product, workload_key, category):
    fids = {f["id"] for f in product.get("findings", [])
            if f["category"] == category and workload_of(f.get("workload")) == workload_key}
    return [e for e in product.get("estimates", []) if e["finding_id"] in fids and e.get("priceable")]


def section_ground_truth(product, rates, d):
    print("## 4. Ground truth: predictions vs measurements\n")
    phase1_rate = rate_for(rates.get("phase1_gpu"), rates) if rates else None
    verdicts = []

    # 4a. Idle and no-pod time on the training job's GPUs.
    print("### 4a. Idle and no-pod GPU time (training job's 2 GPUs)\n")
    ph = phases(os.path.join(d, "train-2gpu.log"))
    findings = product.get("findings", [])
    idle_h = sum((f["window_end"] - f["window_start"]) / 3600 for f in findings
                 if f["category"] == "idle" and workload_of(f.get("workload")) == "train-2gpu")
    nopod_h = sum((f["window_end"] - f["window_start"]) / 3600 for f in findings
                  if f["category"] == "unattributed_gpu_time")
    if "hold_start" in ph and "hold_end" in ph:
        true_idle = 2 * (ph["hold_end"] - ph["hold_start"]) / 3600
        true_nopod = 2 * max(0.0, product.get("exported_at", ph["hold_end"]) - ph["hold_end"]) / 3600
        print("| | Measured (from job log) | Product found | Note |\n|---|---|---|---|")
        print(f"| Idle GPU-hours, pod attached | {true_idle:.1f} | {idle_h:.1f} | product counts whole hourly "
              f"buckets only, and needs the minimum streak first |")
        print(f"| GPU-hours with no pod | {true_nopod:.1f} | {nopod_h:.1f} | until the product data was exported |")
        if phase1_rate:
            print(f"\nIdle cost measured: {inr(true_idle * phase1_rate)} at the real rate; product's idle "
                  f"estimates: {inr(sum(e['amount_inr'] for e in estimates_for(product, 'train-2gpu', 'idle')))}.\n")
    else:
        print("train-2gpu.log missing or the hold phase didn't run -- not run.\n")

    # 4b. Right-sizing: the same load on the recommended GPU.
    print("### 4b. Right-sizing vllm-main: same trace on the recommended GPU\n")
    before, after = summary(os.path.join(d, "load-main.log")), summary(os.path.join(d, "phase2-main.log"))
    run_table([("Phase 1, A100 (before)", before), ("Phase 2, recommended GPU (after)", after)])
    ratio, verdict = compare_runs(before, after)
    over = estimates_for(product, "vllm-main", "over_provisioned")
    rec = None
    if over:
        m = re.search(r"right-size to (.+?)(?: \(|$)", over[-1].get("recommended_action", ""))
        rec = m.group(1).strip() if m else None
    rec_rate = rate_for(rec, rates) if rec else None
    predicted = over[-1]["amount_inr"] if over else None
    measured = (phase1_rate - rec_rate) * HOURS_PER_MONTH if phase1_rate and rec_rate else None
    print(f"Product recommended: **{rec or 'nothing'}**. Predicted monthly saving {inr(predicted)}; "
          f"at the real rental prices in rates.json the switch saves {inr(measured)}/month. "
          f"p95 latency after/before: {fmt(ratio, 2, 'x')}. **Verdict: {verdict}** "
          f"(PASS: p95 <= {P95_PASS}x, errors <= {MAX_ERROR_RATE:.1%}, send lag p95 <= "
          f"{MAX_START_LAG_P95_S:.0f}s; MARGINAL up to {P95_MARGINAL}x).\n")
    verdicts.append(("Right-size vllm-main", predicted, measured if verdict == "PASS" else None, verdict))

    # 4c. Fragmentation: both services co-located on one GPU.
    print("### 4c. Fragmentation: both inference services on one GPU\n")
    pairs = [("vllm-main alone (phase 1)", summary(os.path.join(d, "load-main.log"))),
             ("vllm-main co-located", summary(os.path.join(d, "coloc-main.log"))),
             ("vllm-side alone (phase 1)", summary(os.path.join(d, "load-side.log"))),
             ("vllm-side co-located", summary(os.path.join(d, "coloc-side.log")))]
    run_table(pairs)
    _, v_main = compare_runs(pairs[0][1], pairs[1][1])
    _, v_side = compare_runs(pairs[2][1], pairs[3][1])
    verdict = "PASS" if v_main == v_side == "PASS" else (
        "not run" if "not run" in (v_main, v_side) else ("MARGINAL" if "FAIL" not in (v_main, v_side) else "FAIL"))
    frag = estimates_for(product, "vllm-main", "fragmented") + estimates_for(product, "vllm-side", "fragmented")
    predicted = sum(e["amount_inr"] for e in frag) if frag else None
    measured = phase1_rate * HOURS_PER_MONTH if phase1_rate else None  # one whole GPU freed
    print(f"Product's fragmentation estimates (upper bound) total {inr(predicted)}/month. If co-location "
          f"holds, one whole GPU is freed: {inr(measured)}/month. **Verdict: {verdict}** "
          f"(main: {v_main}, side: {v_side}).\n")
    verdicts.append(("Consolidate main + side", predicted, measured if verdict == "PASS" else None, verdict))

    # 4d. Fewer GPUs for the training job.
    print("### 4d. Multi-GPU training job on fewer GPUs\n")
    runs = [("2 GPUs, 2 workers/GPU (phase 1)", train_summary(os.path.join(d, "train-2gpu.log")), 2),
            ("1 GPU, 2 workers", train_summary(os.path.join(d, "train-1gpu-w2.log")), 1),
            ("1 GPU, 4 workers", train_summary(os.path.join(d, "train-1gpu-w4.log")), 1)]
    print("| Run | Samples/s | Cost per 1M samples |\n|---|---|---|")
    base = runs[0][1]
    best_ratio = None
    for name, s, gpus in runs:
        if not s or not s.get("samples_per_s"):
            print(f"| {name} | not run | |")
            continue
        cost = gpus * phase1_rate / s["samples_per_s"] * 1e6 / 3600 if phase1_rate else None
        print(f"| {name} | {s['samples_per_s']:,.0f} | {inr(cost)} |")
        if gpus == 1 and base and base.get("samples_per_s"):
            r = s["samples_per_s"] / base["samples_per_s"]
            best_ratio = r if best_ratio is None else max(best_ratio, r)
    multi = estimates_for(product, "train-2gpu", "multi_gpu_oversized")
    predicted = sum(e["amount_inr"] for e in multi) if multi else None
    if best_ratio is None:
        verdict = "not run"
    elif best_ratio >= 0.9:
        verdict = "PASS"
    elif best_ratio >= 0.75:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    measured = phase1_rate * HOURS_PER_MONTH if phase1_rate else None
    print(f"\nBest 1-GPU throughput is {fmt(best_ratio * 100 if best_ratio else None, 0, '%')} of the 2-GPU run. "
          f"Product's multi-GPU estimate (upper bound): {inr(predicted)}/month; dropping one GPU saves "
          f"{inr(measured)}/month. **Verdict: {verdict}** (PASS if 1 GPU keeps >= 90% of throughput).\n")
    verdicts.append(("Train on fewer GPUs", predicted, measured if verdict == "PASS" else None, verdict))

    print("## 5. Summary\n")
    print("| Recommendation | Product predicted (₹/month) | Measured, if it holds (₹/month) | Verdict |")
    print("|---|---|---|---|")
    for name, p, m, v in verdicts:
        measured_txt = inr(m) if m is not None else ("did not hold" if v in ("FAIL", "MARGINAL") else "not run")
        print(f"| {name} | {inr(p)} | {measured_txt} | {v} |")
    print()


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 verify.py results/<tag>")
    d = sys.argv[1]
    product = load_json(os.path.join(d, "product.json")) or {}
    rates = load_json(os.path.join(d, "rates.json")) or {}
    print(f"# Client-cluster verification report: {os.path.basename(os.path.normpath(d))}\n")
    if not product:
        print("product.json missing -- export the product's data first (README step 'Collect').\n")
    if not rates:
        print("rates.json missing -- ₹ comparisons skipped. Run rates.py with the real rental prices.\n")
    section_findings(product)
    section_fidelity(product, d)
    section_arithmetic(product, rates)
    section_ground_truth(product, rates, d)


if __name__ == "__main__":
    main()
