"""Compute what fraction of real observed GPU-workload-hours got flagged
by at least one waste category from replay.py's output, merging
overlapping finding windows per (node, gpu, namespace, workload) so an
hour double-flagged by e.g. both idle and fragmentation only counts once.

Usage: python3 summarize.py /path/to/findings.pkl
"""
import pickle
import re
import sys

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

print(f"total observed GPU-workload-hours (rollup rows): {total_rollup_rows}")
print(f"distinct (node,gpu,ns,workload) keys with >=1 finding: {len(intervals)}")
print(f"total flagged hours (merged, no double-counting overlap): {total_flagged_hours:.0f}")
print(f"fraction of observed capacity-hours flagged as some form of waste: {100*total_flagged_hours/total_rollup_rows:.1f}%")
