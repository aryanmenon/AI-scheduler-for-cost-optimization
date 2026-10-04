"""Export everything the product concluded, as one JSON document on stdout.

Runs INSIDE the product's savings-estimator container (it mounts all three
databases read-only or read-write), fed over stdin -- no copy into the pod
needed:

  kubectl -n gpu-optimizer exec -i deploy/gpuopt-collector -c savings-estimator \\
    -- python3 - < dump_product_data.py > results/<tag>/product.json

Contents: every waste finding, every savings estimate, and the hourly
rollups (per GPU per workload) -- the last so verify.py can compare the
product's measured utilization with an independent nvidia-smi log.
Standard library only.
"""
import json
import os
import sqlite3
import time

# /data inside the product pod; override only to run against local copies.
ROOT = os.environ.get("PRODUCT_DATA_ROOT", "/data")

SOURCES = {
    "findings": (f"{ROOT}/findings/findings.db", "SELECT * FROM waste_findings ORDER BY id"),
    "estimates": (f"{ROOT}/savings/savings.db", "SELECT * FROM savings_estimates ORDER BY id"),
    "hourly_rollups": (f"{ROOT}/normalized/normalized.db",
                       "SELECT * FROM rollups WHERE granularity = 'hourly' ORDER BY bucket_start"),
}

out = {"exported_at": time.time()}
for key, (path, query) in SOURCES.items():
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        out[key] = [dict(r) for r in conn.execute(query).fetchall()]
        conn.close()
    except sqlite3.Error as exc:
        out[key] = []
        out.setdefault("errors", {})[key] = str(exc)
print(json.dumps(out))
