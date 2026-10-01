"""Compute what fraction of real observed GPU-workload-hours got flagged
by at least one waste category from replay.py's output, merging
overlapping finding windows per (node, gpu, namespace, workload) so an
hour double-flagged by e.g. both idle and fragmentation only counts once.

If replay.py's rollups.pkl sits next to findings.pkl, it also prints a
unified breakdown: every tier measured in one unit (GPU capacity left
unused below the 70% efficient-use target), so the tiers can be added up
into a single "total waste detected" figure without double-counting.

Usage: python3 summarize.py /path/to/findings.pkl
"""
import os
import pickle
import re
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "waste-detector", "src"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "ingestion-normalization", "src"))

if len(sys.argv) < 2:
    print("usage: python3 summarize.py /path/to/findings.pkl", file=sys.stderr)
    sys.exit(1)

with open(sys.argv[1], "rb") as f:
    data = pickle.load(f)

BUCKET = 3600
total_rollup_rows = data["rollup_row_count"]

# key -> list of (start, end) intervals to merge
intervals = {}


def add(finding, start=None, end=None):
    key = (finding.node, finding.gpu_index, finding.namespace, finding.workload)
    s = finding.window_start if start is None else start
    e = finding.window_end if end is None else end
    intervals.setdefault(key, []).append((s, e))


pattern_re = re.compile(r"on (\d+)/(\d+) observed days")

for finding in data["idle"]:
    add(finding)
for finding in data["over_provisioned"]:
    add(finding)
for finding in data["fragmented"]:
    add(finding)
for finding in data["recurring_pattern"]:
    # window spans the whole multi-day observation period, but this
    # category only actually flags ONE hour-of-day per day -- use the
    # parsed "X/Y observed days" count as X discrete 1h intervals
    # anchored at window_start (exact placement doesn't matter for a
    # union-of-hours count, only the total distinct-hour contribution
    # from this finding within its own key).
    m = pattern_re.search(finding.detail)
    n_days = int(m.group(1)) if m else 0
    for i in range(n_days):
        add(finding, start=finding.window_start + i * BUCKET, end=finding.window_start + (i + 1) * BUCKET)

total_flagged_hours = 0.0
for key, ivs in intervals.items():
    ivs.sort()
    merged = []
    for s, e in ivs:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    total_flagged_hours += sum((e - s) / BUCKET for s, e in merged)

# multi_gpu_oversized is visibility-only (an upper bound sized on hourly
# averages) and is reported separately, never folded into the flagged-waste
# percentage above. Each finding covers one GPU of a multi-GPU job and its
# metric_value is the fraction of the job's GPUs that could be released, so
# releasable GPU-hours = sum over that GPU's hours of the fraction. Hours
# already flagged by an actionable category are skipped so the two figures
# can be added without double-counting.
flagged_units = set()
for key, ivs in intervals.items():
    for s, e in ivs:
        t = s
        while t < e:
            flagged_units.add((key, t))
            t += BUCKET
multi_total = 0.0
multi_new = 0.0
for finding in data.get("multi_gpu_oversized", []):
    key = (finding.node, finding.gpu_index, finding.namespace, finding.workload)
    t = finding.window_start
    while t < finding.window_end:
        multi_total += finding.metric_value
        if (key, t) not in flagged_units:
            multi_new += finding.metric_value
        t += BUCKET

print(f"total observed GPU-workload-hours (rollup rows): {total_rollup_rows}")
print(f"distinct (node,gpu,ns,workload) keys with >=1 finding: {len(intervals)}")
print(f"total flagged hours (merged, no double-counting overlap): {total_flagged_hours:.0f}")
print(f"fraction of observed capacity-hours flagged as some form of waste: {100*total_flagged_hours/total_rollup_rows:.1f}%")
if "multi_gpu_oversized" in data:
    print(f"multi-GPU oversized findings (visibility only, NOT in the figure above): {len(data['multi_gpu_oversized'])}")
    print(f"  releasable GPU-hours (upper bound): {multi_total:.0f} ({100*multi_total/total_rollup_rows:.1f}%), "
          f"of which not already flagged above: {multi_new:.0f} ({100*multi_new/total_rollup_rows:.1f}%)")

# The "below actionable recommendations" tier: GPU-hours below the
# efficient-use target that no finding above explains (detected, no
# recommendation). Its hours never overlap the actionable or multi-GPU
# findings' (the detector excludes them), so it adds without double-counting.
tier = data.get("underutilized", []) + data.get("unattributed_gpu_time", [])
if "underutilized" in data:
    tier_hours = 0.0
    tier_capacity = 0.0
    for finding in tier:
        hours = (finding.window_end - finding.window_start) / BUCKET
        tier_hours += hours
        tier_capacity += hours * finding.metric_value
    multi_units = set()
    for finding in data.get("multi_gpu_oversized", []):
        key = (finding.node, finding.gpu_index, finding.namespace, finding.workload)
        t = finding.window_start
        while t < finding.window_end:
            multi_units.add((key, t))
            t += BUCKET
    any_waste = len(flagged_units | multi_units) + tier_hours
    print(f"below-target, no recommendation (underutilized + unattributed): {len(tier)} findings, "
          f"{tier_hours:.0f} GPU-hours ({100*tier_hours/total_rollup_rows:.1f}%), "
          f"unused capacity below target {tier_capacity:.0f} GPU-hours ({100*tier_capacity/total_rollup_rows:.1f}%)")
    # A coverage figure, not an amount of waste: a multi-GPU finding touches
    # every GPU of the job even though only a fraction is releasable.
    print(f"coverage: GPU-hours touched by at least one finding in any tier: "
          f"{any_waste:.0f} ({100*any_waste/total_rollup_rows:.1f}%) -- not an amount of waste")

# Unified breakdown: one unit for every tier. Each usable GPU-hour's
# shortfall below the target, (target - avg utilization) / 100 of a GPU,
# is assigned to the most trusted tier whose findings cover that hour, so
# nothing is counted twice and the tiers add up. Hours below the minimum
# coverage ratio are reported as "not checked" -- every detector skips
# them on purpose -- rather than silently dropped.
rollups_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "rollups.pkl")
if os.path.exists(rollups_path) and "underutilized" in data:
    from waste_detector.unrecommended import covered_units, _unit  # noqa: E402

    TARGET_PCT = 70.0        # waste_detector Config.underutilized_target_pct default
    MIN_COVERAGE = 0.8       # replay.py's Config.min_coverage_ratio

    with open(rollups_path, "rb") as f:
        rollup_rows = pickle.load(f)

    tiers = [
        ("actionable (idle, over-provisioned, recurring, fragmentation)",
         covered_units(data["idle"] + data["over_provisioned"] + data["fragmented"] + data["recurring_pattern"])),
        ("multi-GPU jobs, could use fewer GPUs (review)", covered_units(data["multi_gpu_oversized"])),
        ("detected, no recommendation yet", covered_units(data["underutilized"] + data["unattributed_gpu_time"])),
    ]
    by_tier = [0.0] * len(tiers)
    undetected = 0.0
    not_checked = 0.0
    raw_unused = 0.0
    for r in rollup_rows:
        if r.avg_utilization_pct is None:
            continue
        raw_unused += (100.0 - r.avg_utilization_pct) / 100.0
        shortfall = max(0.0, (TARGET_PCT - r.avg_utilization_pct) / 100.0)
        if shortfall == 0.0:
            continue
        if r.coverage_ratio < MIN_COVERAGE:
            not_checked += shortfall
            continue
        unit = _unit(r.node, r.gpu_index, r.gpu_instance_id, r.namespace, r.workload, r.bucket_start)
        for i, (_, covered) in enumerate(tiers):
            if unit in covered:
                by_tier[i] += shortfall
                break
        else:
            undetected += shortfall

    total_waste = sum(by_tier) + undetected + not_checked
    detected = sum(by_tier)

    def pct(x, of=total_rollup_rows):
        return 100.0 * x / of if of else 0.0

    print()
    print(f"UNIFIED BREAKDOWN (GPU capacity unused below the {TARGET_PCT:.0f}% target):")
    print(f"  total waste: {total_waste:.0f} GPU-hours = {pct(total_waste):.1f}% of capacity "
          f"(raw unused capacity incl. above-target slack: {pct(raw_unused):.1f}%)")
    for (name, _), amount in zip(tiers, by_tier):
        print(f"  {name}: {pct(amount):.1f}% of capacity ({pct(amount, total_waste):.0f}% of waste)")
    print(f"  TOTAL DETECTED: {pct(detected):.1f}% of capacity ({pct(detected, total_waste):.0f}% of waste)")
    print(f"  not checked (coverage < {MIN_COVERAGE:.0%}): {pct(not_checked):.1f}% of capacity "
          f"({pct(not_checked, total_waste):.0f}% of waste)")
    print(f"  below target in checked hours but undetected: {pct(undetected):.1f}% of capacity")

