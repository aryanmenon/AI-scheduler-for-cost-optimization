"""One side of the right-sizing mini-test: serve a model with vLLM on this
machine's GPU, replay the real Azure trace at it, log GPU busy % the whole
time, and print one RESULT_JSON line with everything compare.py needs.

Run the identical command on the "before" GPU and on the GPU the product
recommends; only --label and --gpu-mem differ. Needs trace_load.py (from
testing/client-cluster-verification-test/) in the same directory.
Standard library only; installs vllm itself if it's missing.

  python3 rightsize_minitest.py --label cal --minutes 5      # calibrate load
  python3 rightsize_minitest.py --label before --minutes 30  # the real run

The vLLM server is left running between invocations (so a calibration run
doesn't pay model load twice); --stop-server shuts it down at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VLLM_VERSION = "0.8.5.post1"  # same pin as the client-cluster kit's image
# The product's telemetry collector scrapes DCGM every 30 s by default
# (deploy/helm/gpu-telemetry-collector/values.yaml scrapeIntervalSeconds),
# and over_provisioning.py takes the max of those samples as the peak.
PRODUCT_SCRAPE_SEC = 30


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def server_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_vllm() -> str:
    try:
        out = subprocess.run([sys.executable, "-c", "import vllm; print(vllm.__version__)"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except subprocess.CalledProcessError:
        log(f"installing vllm=={VLLM_VERSION} (several minutes) ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", f"vllm=={VLLM_VERSION}"], check=True)
        return VLLM_VERSION


def start_server(args) -> None:
    if server_up(args.port):
        log(f"vLLM already serving on :{args.port}, reusing it")
        return
    env = dict(os.environ, VLLM_USE_V1="0")  # V0 engine: runs on T4 (compute 7.5) too
    cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server",
           "--model", args.model, "--served-model-name", "main",
           "--dtype", "half", "--max-model-len", "4096", "--max-num-seqs", "64",
           "--gpu-memory-utilization", str(args.gpu_mem), "--port", str(args.port)]
    logf = open(f"vllm-{args.label}.log", "w")
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, env=env)
    log(f"starting vLLM (log: vllm-{args.label}.log) ...")
    deadline = time.time() + 1800
    while not server_up(args.port):
        if proc.poll() is not None:
            with open(f"vllm-{args.label}.log") as f:
                tail = f.read()[-3000:]
            raise SystemExit(f"vLLM exited with code {proc.returncode}. Last log lines:\n{tail}")
        if time.time() > deadline:
            raise SystemExit("vLLM not ready after 30 min")
        time.sleep(10)
    log("vLLM ready")


def gpu_info() -> dict:
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
    name, driver, mem = [x.strip() for x in out.stdout.splitlines()[0].split(",")]
    return {"gpu_name": name, "driver": driver, "gpu_memory_mib": float(mem)}


def util_stats(path: str) -> dict:
    util, mem = [], []
    with open(path) as f:
        for line in f:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                util.append(float(parts[0]))
                mem.append(float(parts[1]))
            except ValueError:
                continue
    if not util:
        return {"samples": 0}
    # What the product would have seen: one sample every 30 s. The phase of
    # those 30 s ticks relative to the load is arbitrary, so report the
    # median and the max of the peak across all 30 possible phases.
    phase_peaks = [max(util[o::PRODUCT_SCRAPE_SEC]) for o in range(min(PRODUCT_SCRAPE_SEC, len(util)))]
    srt = sorted(util)
    return {
        "samples": len(util),
        "mean_pct": round(statistics.fmean(util), 2),
        "p95_1s_pct": srt[min(len(srt) - 1, round(0.95 * (len(srt) - 1)))],
        "max_1s_pct": max(util),
        "product_peak_median_pct": statistics.median(phase_peaks),
        "product_peak_max_pct": max(phase_peaks),
        "memory_used_max_mib": max(mem),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True, help="e.g. cal, before, after")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--keep-fraction", type=float, default=0.05,
                    help="fraction of trace rows replayed; lower = lighter load")
    ap.add_argument("--gpu-mem", type=float, default=0.50,
                    help="vLLM --gpu-memory-utilization; pick so both GPUs get ~12 GB")
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--trace", default="conv")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--stop-server", action="store_true")
    args = ap.parse_args()

    trace_load = os.path.join(HERE, "trace_load.py")
    if not os.path.exists(trace_load):
        raise SystemExit("trace_load.py must be in the same directory as this script")

    info = gpu_info()
    log(f"GPU: {info['gpu_name']} (driver {info['driver']}, {info['gpu_memory_mib']:.0f} MiB)")
    version = ensure_vllm()
    start_server(args)

    # Log only while the trace runs: model loading would pollute the peak.
    gpu_csv = f"gpu-{args.label}.csv"
    smi = subprocess.Popen(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits", "-l", "1"],
                           stdout=open(gpu_csv, "w"), stderr=subprocess.DEVNULL)
    log(f"replaying {args.trace} trace, keep {args.keep_fraction}, {args.minutes} min ...")
    summary = None
    with open(f"load-{args.label}.log", "w") as lf:
        proc = subprocess.Popen(
            [sys.executable, trace_load, "--target", f"http://localhost:{args.port}", "--model", "main",
             "--trace", args.trace, "--label", args.label, "--keep-fraction", str(args.keep_fraction),
             "--duration-hours", str(args.minutes / 60.0), "--summary-every-sec", "60"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            lf.write(line)
            if line.startswith("SUMMARY_JSON "):
                summary = json.loads(line[len("SUMMARY_JSON "):])
            elif line.startswith("INTERVAL_JSON "):
                iv = json.loads(line[len("INTERVAL_JSON "):])
                log(f"  {iv['requests']} req, p95 {iv['latency_p95_s'] or 0:.2f}s, errors {iv['errors']}")
            else:
                print(line, end="", flush=True)
        proc.wait()
    smi.terminate()
    smi.wait()
    if summary is None:
        raise SystemExit(f"no SUMMARY_JSON from trace_load (see load-{args.label}.log)")

    result = {"label": args.label, **info, "vllm": version, "model": args.model,
              "gpu_mem_fraction": args.gpu_mem, "keep_fraction": args.keep_fraction,
              "minutes": args.minutes, "util": util_stats(gpu_csv), "load": summary}
    with open(f"result-{args.label}.json", "w") as f:
        json.dump(result, f, indent=2)
    u = result["util"]
    log(f"busy %: mean {u.get('mean_pct')}, product-style peak {u.get('product_peak_median_pct')} "
        f"(1 s max {u.get('max_1s_pct')}); p95 latency {summary['latency_p95_s']}s, "
        f"errors {summary['errors']}/{summary['requests']}")
    print("RESULT_JSON " + json.dumps(result), flush=True)

    if args.stop_server:
        subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"])


if __name__ == "__main__":
    main()
