"""Replay the real Azure LLM inference trace against a vLLM OpenAI-compatible
server and record what the client actually experienced.

Built for the client-cluster verification test: the same trace, at the same
speed, is replayed against the "before" GPU and against whatever GPU the
product recommends, so latency, throughput and error rates can be compared
like for like. Standard library only, so it runs in a plain python image.

Each trace row is (timestamp, ContextTokens, GeneratedTokens). A request is
sent at the row's real offset (divided by --speed) with:
- a prompt of exactly ContextTokens token IDs (clipped so prompt + output
  fits --max-model-len). The trace has no prompt text, only sizes, and
  sending token IDs keeps the real compute size without needing a tokenizer;
- max_tokens = min(GeneratedTokens, --max-new-tokens-cap) and
  ignore_eos=true, so every run generates exactly the same number of tokens
  regardless of which GPU or model build serves it.

The trace spans ~58 minutes; --duration-hours loops it back to back.

Output, one JSON object per line on stdout:
  INTERVAL_JSON {...}  every --summary-every-sec (rolling window)
  SUMMARY_JSON {...}   once at the end (whole run)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

TRACE_URLS = {
    "conv": "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/AzureLLMInferenceTrace_conv.csv",
    "code": "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/AzureLLMInferenceTrace_code.csv",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}", flush=True)


def _parse_ts(raw: str) -> float:
    # The trace uses 7-digit fractional seconds, which datetime can't parse.
    raw = raw.strip()
    if "." in raw:
        head, frac = raw.split(".", 1)
        raw = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(raw).timestamp()


def load_trace(source: str, keep_fraction: float, seed: int) -> list[tuple[float, int, int]]:
    if source in TRACE_URLS:
        with urllib.request.urlopen(TRACE_URLS[source], timeout=120) as resp:
            text = resp.read().decode()
    else:
        with open(source) as f:
            text = f.read()
    rng = random.Random(seed)
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        if keep_fraction < 1.0 and rng.random() > keep_fraction:
            continue
        rows.append((_parse_ts(rec["TIMESTAMP"]), int(rec["ContextTokens"]), int(rec["GeneratedTokens"])))
    rows.sort()
    start = rows[0][0]
    return [(ts - start, ctx, gen) for ts, ctx, gen in rows]


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = min(len(values) - 1, max(0, round(p / 100.0 * (len(values) - 1))))
    return values[k]


def summarize(records: list[dict], wall_seconds: float) -> dict:
    ok = [r for r in records if r["ok"]]
    lat = [r["latency_s"] for r in ok]
    late = [r["start_lag_s"] for r in records]
    out_tokens = sum(r["completion_tokens"] for r in ok)
    return {
        "requests": len(records),
        "ok": len(ok),
        "errors": len(records) - len(ok),
        "error_rate": (len(records) - len(ok)) / len(records) if records else None,
        "latency_p50_s": _pct(lat, 50),
        "latency_p95_s": _pct(lat, 95),
        "latency_p99_s": _pct(lat, 99),
        "latency_mean_s": statistics.fmean(lat) if lat else None,
        # How far behind schedule requests were sent: grows when the client's
        # own concurrency limit is saturated, i.e. the server isn't keeping up.
        "start_lag_p95_s": _pct(late, 95),
        "output_tokens": out_tokens,
        "output_tokens_per_s": out_tokens / wall_seconds if wall_seconds > 0 else None,
        "wall_seconds": wall_seconds,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="vLLM base URL, e.g. http://vllm-main:8000")
    ap.add_argument("--model", required=True, help="served model name")
    ap.add_argument("--trace", default="conv", help="'conv', 'code', or a local CSV path")
    ap.add_argument("--label", default="run", help="tag copied into every JSON line")
    ap.add_argument("--max-model-len", type=int, default=4096)
    ap.add_argument("--max-new-tokens-cap", type=int, default=256)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--keep-fraction", type=float, default=1.0,
                    help="replay only this random fraction of rows (lighter load)")
    ap.add_argument("--duration-hours", type=float, default=None,
                    help="loop the trace until this much wall time has passed (default: one pass)")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--summary-every-sec", type=float, default=300.0)
    ap.add_argument("--vocab-low", type=int, default=1000)
    ap.add_argument("--vocab-high", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--wait-ready-sec", type=float, default=1800.0,
                    help="poll /v1/models until the server answers (model download/load)")
    args = ap.parse_args()

    rows = load_trace(args.trace, args.keep_fraction, args.seed)
    span = rows[-1][0]
    log(f"{len(rows)} trace rows, span {span / 60:.1f} min, speed {args.speed}x, label {args.label}")

    deadline = time.time() + args.wait_ready_sec
    while True:
        try:
            with urllib.request.urlopen(f"{args.target}/v1/models", timeout=10) as r:
                if r.status == 200:
                    break
        except Exception:
            pass
        if time.time() > deadline:
            raise SystemExit(f"server at {args.target} not ready after {args.wait_ready_sec}s")
        time.sleep(10)
    log("server ready")

    rng = random.Random(args.seed)
    records: list[dict] = []
    window: list[dict] = []
    lock = threading.Lock()
    url = f"{args.target}/v1/completions"

    def fire(scheduled_at: float, ctx: int, gen: int) -> None:
        max_tokens = max(1, min(gen, args.max_new_tokens_cap))
        ctx = max(1, min(ctx, args.max_model_len - max_tokens - 8))
        with lock:
            prompt = [rng.randint(args.vocab_low, args.vocab_high) for _ in range(ctx)]
        body = json.dumps({
            "model": args.model, "prompt": prompt, "max_tokens": max_tokens,
            "temperature": 0.0, "ignore_eos": True,
        }).encode()
        start = time.time()
        rec = {"start_lag_s": max(0.0, start - scheduled_at), "ok": False, "completion_tokens": 0}
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as resp:
                payload = json.loads(resp.read())
            rec["ok"] = True
            rec["completion_tokens"] = int(payload.get("usage", {}).get("completion_tokens", 0))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            rec["error"] = str(exc)[:200]
        rec["latency_s"] = time.time() - start
        with lock:
            records.append(rec)
            window.append(rec)

    run_start = time.time()
    end_at = run_start + args.duration_hours * 3600 if args.duration_hours else None
    last_summary = run_start
    loop = 0
    past_deadline = False
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        while not past_deadline:
            loop_start = time.time()
            for offset, ctx, gen in rows:
                scheduled = loop_start + offset / args.speed
                now = time.time()
                if end_at and scheduled > end_at:
                    # Stop the whole run, not just this pass -- otherwise the
                    # outer loop would immediately start another pass.
                    past_deadline = True
                    break
                if scheduled > now:
                    time.sleep(scheduled - now)
                pool.submit(fire, scheduled, ctx, gen)
                if time.time() - last_summary >= args.summary_every_sec:
                    with lock:
                        snap = list(window)
                        window.clear()
                    interval = summarize(snap, time.time() - last_summary)
                    interval.update({"label": args.label, "loop": loop, "t": time.time()})
                    print("INTERVAL_JSON " + json.dumps(interval), flush=True)
                    last_summary = time.time()
            loop += 1
            if not end_at or time.time() >= end_at:
                break
        log("all requests dispatched, waiting for in-flight completions ...")

    final = summarize(records, time.time() - run_start)
    final.update({"label": args.label, "loops": loop, "model": args.model, "target": args.target,
                  "speed": args.speed, "keep_fraction": args.keep_fraction, "started": run_start,
                  "ended": time.time()})
    print("SUMMARY_JSON " + json.dumps(final), flush=True)


if __name__ == "__main__":
    main()
