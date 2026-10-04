"""Build docs/pilot/sample-report.html: the real product pipeline (waste-
detector -> savings-estimator -> dashboard) run over a FICTIONAL 8-day,
7-GPU cluster, for showing prospects what a pilot report looks like.

Every finding, rupee figure and recommendation in the output is computed by
the product's own code; only the hourly utilization/memory input is made
up. Prices are the product's illustrative INR rates, not any real customer's.

  python3 docs/pilot/make_sample_report.py
"""
from __future__ import annotations

import math
import os
import random
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for sub in ("ingestion-normalization", "waste-detector", "savings-estimator", "dashboard"):
    sys.path.insert(0, os.path.join(REPO, sub, "src"))

from dashboard.aggregator import aggregate  # noqa: E402
from dashboard.render import render_report  # noqa: E402
from dashboard.report_reader import ReportReader  # noqa: E402
from ingestion_normalization.rollup import RollupRecord  # noqa: E402
from ingestion_normalization.storage import NormalizedStorage  # noqa: E402
from savings_estimator.config import Config as SavingsConfig  # noqa: E402
from savings_estimator.findings_reader import FindingsReader  # noqa: E402
from savings_estimator.pipeline import run_once as savings_run_once  # noqa: E402
from savings_estimator.rollup_reader import RollupReader as SavingsRollupReader  # noqa: E402
from savings_estimator.storage import SavingsStorage  # noqa: E402
from waste_detector.config import Config as WasteConfig  # noqa: E402
from waste_detector.findings import FindingsStorage  # noqa: E402
from waste_detector.pipeline import run_once as waste_run_once  # noqa: E402
from waste_detector.rollup_reader import RollupReader as WasteRollupReader  # noqa: E402

HOURS = 8 * 24
START = 1_790_000_000 - (1_790_000_000 % 86400)  # a UTC midnight
GPUS = {  # (node, gpu) -> (model, fp16 TFLOPS, MiB usable)
    ("gpu-a100-1", "0"): ("NVIDIA A100-SXM4-80GB", 312.0, 81920.0),
    ("gpu-a100-1", "1"): ("NVIDIA A100-SXM4-80GB", 312.0, 81920.0),
    ("gpu-a100-2", "0"): ("NVIDIA A100-SXM4-80GB", 312.0, 81920.0),
    ("gpu-a100-2", "1"): ("NVIDIA A100-SXM4-80GB", 312.0, 81920.0),
    ("gpu-l4-1", "0"): ("NVIDIA L4", 121.0, 23034.0),
    ("gpu-l4-1", "1"): ("NVIDIA L4", 121.0, 23034.0),
    ("gpu-t4-1", "0"): ("Tesla T4", 65.0, 15360.0),
}


def workload_hour(node, gpu, h, rng):
    """(namespace, workload, avg %, max %, peak memory MiB) for one GPU-hour."""
    hod = h % 24
    if (node, gpu) == ("gpu-a100-1", "0"):  # vLLM chat API: low average, busy whenever a request runs
        avg = 12 + 10 * math.sin(math.pi * max(0, hod - 6) / 16) + rng.uniform(-2, 2)
        return "chat", "llm-chat-api", avg, min(100, 70 + rng.uniform(0, 25)), 0.9 * 81920
    if (node, gpu) == ("gpu-a100-1", "1"):  # embeddings service, oversized
        return "search", "embeddings", 6 + rng.uniform(-2, 2), 18 + rng.uniform(0, 6), 9000 + rng.uniform(0, 600)
    if (node, gpu) == ("gpu-a100-2", "0"):  # nightly-quiet training box
        busy = 75 + rng.uniform(-5, 5) if 8 <= hod < 22 else rng.uniform(0, 1.5)
        return "research", "finetune-runner", busy, min(100, busy + 10), 60000.0
    if (node, gpu) == ("gpu-a100-2", "1"):  # abandoned notebook from day 3
        if h < 48:
            return "research", "notebook-priya", 40 + rng.uniform(-5, 5), 80.0, 30000.0
        return "research", "notebook-priya", rng.uniform(0, 1), 1.5, 30000.0
    if node == "gpu-l4-1":  # two small services, each on its own L4
        name = "ocr-worker" if gpu == "0" else "reranker"
        avg = 18 + rng.uniform(-4, 4)
        return "docs", name, avg, avg + 20, 4000.0
    return "batch", "video-transcode", 82 + rng.uniform(-5, 5), 98.0, 12000.0  # healthy T4


def main() -> None:
    rng = random.Random(42)
    tmp = tempfile.mkdtemp()
    normalized, findings, savings = (os.path.join(tmp, n) for n in ("n.db", "f.db", "s.db"))

    rows = []
    for h in range(HOURS):
        for (node, gpu), (model, tflops, total) in GPUS.items():
            ns, wl, avg, mx, mem = workload_hour(node, gpu, h, rng)
            avg = max(0.0, min(100.0, avg))
            rows.append(RollupRecord(
                bucket_start=START + h * 3600.0, node=node, gpu_index=gpu, gpu_instance_id=None,
                namespace=ns, workload=wl, sample_count=120, expected_sample_count=120.0,
                coverage_ratio=1.0, low_confidence=False, avg_utilization_pct=avg,
                max_utilization_pct=max(avg, min(100.0, mx)), avg_memory_used_mb=mem * 0.9,
                avg_power_draw_w=150.0, avg_effective_tflops=avg / 100 * tflops, gpu_model=model,
                fp16_tflops=tflops, max_memory_used_mb=mem, memory_total_mb=total))
    store = NormalizedStorage(normalized)
    store.replace_rollups("hourly", START, START + HOURS * 3600.0, rows)
    store.close()

    wcfg = WasteConfig.from_env()
    wcfg = WasteConfig(**{**wcfg.__dict__, "normalized_sqlite_path": normalized,
                          "findings_sqlite_path": findings, "findings_retention_hours": 0,
                          "heartbeat_path": os.path.join(tmp, "hb1")})
    fs, wr = FindingsStorage(findings), WasteRollupReader(normalized)
    waste_run_once(wcfg, wr, fs)
    wr.close(); fs.close()

    scfg = SavingsConfig.from_env()
    scfg = SavingsConfig(**{**scfg.__dict__, "findings_sqlite_path": findings,
                            "normalized_sqlite_path": normalized, "savings_sqlite_path": savings,
                            "savings_estimates_retention_hours": 0, "heartbeat_path": os.path.join(tmp, "hb2")})
    ss, fr, sr = SavingsStorage(savings), FindingsReader(findings), SavingsRollupReader(normalized)
    savings_run_once(scfg, fr, sr, ss)
    fr.close(); sr.close(); ss.close()

    estimates = ReportReader(savings).all_estimates()
    if os.environ.get("DUMP"):
        for e in sorted(estimates, key=lambda e: (e.category, e.workload or "")):
            print(f"{e.category:22} {e.workload or '-':18} {e.node}/{e.gpu_index} "
                  f"{(e.window_end - e.window_start) / 3600:5.0f}h Rs{e.amount_inr or 0:>11,.0f} {e.basis} | {e.recommended_action[:90]}")
    html = render_report(aggregate(estimates, top_n=15))
    banner = ('<div style="background:#7c2d12;color:#fff;padding:10px 16px;font:600 14px sans-serif">'
              "SAMPLE REPORT &middot; fictional 7-GPU cluster, 8 days of made-up utilization &middot; "
              "every finding and &#8377; figure below is computed by the product's real pipeline &middot; "
              "illustrative INR rates, not a real customer's</div>")
    html = html.replace("<body>", "<body>" + banner, 1) if "<body>" in html else banner + html
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample-report.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
