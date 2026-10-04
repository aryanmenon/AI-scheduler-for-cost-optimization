"""Re-run every waste detector on the hourly rollups replay.py saved
(rollups.pkl), without re-downloading or re-reading the Philly trace.

Uses the same real pilot thresholds as replay.py and writes findings.pkl
in the format summarize.py reads.

Usage: python3 rerun_detectors.py /path/to/output_dir   (holding rollups.pkl)
"""
import os
import pickle
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "waste-detector", "src"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "ingestion-normalization", "src"))

from waste_detector.config import Config  # noqa: E402
from waste_detector.fragmentation import detect_fragmentation  # noqa: E402
from waste_detector.idle import detect_idle  # noqa: E402
from waste_detector.multi_gpu import detect_multi_gpu_oversized  # noqa: E402
from waste_detector.over_provisioning import detect_over_provisioning, detect_oversized_by_average  # noqa: E402
from waste_detector.patterns import detect_recurring_patterns  # noqa: E402
from waste_detector.unrecommended import detect_unrecommended_waste  # noqa: E402

if len(sys.argv) < 2:
    print("usage: python3 rerun_detectors.py /path/to/output_dir", file=sys.stderr)
    sys.exit(1)

out_dir = sys.argv[1]
with open(os.path.join(out_dir, "rollups.pkl"), "rb") as f:
    rollup_rows = pickle.load(f)

# Must match replay.py's Config exactly.
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

findings = {
    "idle": detect_idle(rollup_rows, config),
    "over_provisioned": detect_over_provisioning(rollup_rows, config),
    "oversized_by_average": detect_oversized_by_average(rollup_rows, config),
    "fragmented": detect_fragmentation(rollup_rows, config),
    "recurring_pattern": detect_recurring_patterns(rollup_rows, config),
    "multi_gpu_oversized": detect_multi_gpu_oversized(rollup_rows, config),
}
# Last, over everything above -- same order as waste_detector.detector.
already = [f for items in findings.values() for f in items]
tier = detect_unrecommended_waste(rollup_rows, already, config)
findings["underutilized"] = [f for f in tier if f.category == "underutilized"]
findings["unattributed_gpu_time"] = [f for f in tier if f.category == "unattributed_gpu_time"]
for name, items in findings.items():
    print(f"{name} findings: {len(items)}")

findings["rollup_row_count"] = len(rollup_rows)
with open(os.path.join(out_dir, "findings.pkl"), "wb") as f:
    pickle.dump(findings, f)
print(f"saved findings to {os.path.join(out_dir, 'findings.pkl')}")
