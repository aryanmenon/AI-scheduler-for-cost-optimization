"""Replays a real Azure LLM-inference request-arrival trace against a real
GPU-backed inference server, preserving real inter-arrival timing and real
per-request token sizes.

Unlike testing/real-trace-replay (which replays already-recorded real
*utilization* numbers offline, no GPU needed), this drives a live server
with real request *arrival patterns* so the utilization it produces is
genuinely caused by real traffic shape, not this project's own randomized
load_generator.py bursts. The tradeoff: it needs a real rented GPU and
runs in roughly real time (or --speed times faster), unlike the Philly
replay's ~10-minute offline pass over the full dataset.

The trace has no prompt text (Microsoft stripped it for privacy) -- only
TIMESTAMP, ContextTokens, GeneratedTokens per real request. This script
reconstructs a prompt of the real ContextTokens length by slicing a long
filler passage at the exact token boundary using the SAME tokenizer the
target server uses, and requests exactly GeneratedTokens as max_new_tokens
(both clipped to whatever the serving model can actually handle -- see
--max-context-tokens below, which you must determine empirically for your
model before the real run; see README "Before the real run").
"""
from __future__ import annotations

import argparse
import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _parse_timestamp(raw: str) -> datetime:
    # The real Azure trace's TIMESTAMP column uses 7-digit fractional
    # seconds (.NET-style 100ns ticks, e.g. "18:15:46.6805900") --
    # Python's %f only parses up to 6-digit microseconds, so a 7-digit
    # value fails with "unconverted data remains: 0". Truncate to 6
    # digits (microsecond precision is more than enough here) before
    # parsing rather than losing the sub-second ordering entirely.
    date_part, _, frac_part = raw.partition(".")
    return datetime.strptime(f"{date_part}.{frac_part[:6]}", "%Y-%m-%d %H:%M:%S.%f")


def load_trace(path: str, limit: int | None) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "timestamp": _parse_timestamp(row["TIMESTAMP"]),
                    "context_tokens": int(row["ContextTokens"]),
                    "generated_tokens": int(row["GeneratedTokens"]),
                }
            )
            if limit and len(rows) >= limit:
                break
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def build_prompt_bank(tokenizer, max_context_tokens: int) -> list[int]:
    """A long token-id sequence to slice prompts of any length <= max_context_tokens from."""
    filler = "The quick brown fox jumps over the lazy dog. " * (max_context_tokens // 8 + 20)
    ids = tokenizer(filler, add_special_tokens=False)["input_ids"]
    if len(ids) < max_context_tokens:
        raise ValueError(
            f"filler text only tokenized to {len(ids)} tokens, need {max_context_tokens} -- "
            "increase the filler repeat count above"
        )
    return ids


def fire(
    session: requests.Session,
    url: str,
    tokenizer,
    prompt_bank: list[int],
    context_tokens: int,
    max_new_tokens: int,
    stats: dict,
    stats_lock: threading.Lock,
) -> None:
    prompt = tokenizer.decode(prompt_bank[:context_tokens])
    try:
        resp = session.post(
            url, json={"prompt": prompt, "max_new_tokens": max_new_tokens}, timeout=120
        )
        ok = resp.status_code == 200
    except requests.RequestException as e:
        ok = False
        log(f"request failed: {e}")
    with stats_lock:
        stats["sent"] += 1
        stats["ok"] += 1 if ok else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace_csv", help="AzureLLMInferenceTrace_conv.csv or _code.csv")
    parser.add_argument("--target", required=True, help="e.g. http://localhost:8001/generate")
    parser.add_argument("--model-name", default="sshleifer/tiny-gpt2",
                         help="must match the server's MODEL_NAME -- prompts are tokenized with this")
    parser.add_argument("--max-context-tokens", type=int, required=True,
                         help="clip real ContextTokens to this -- determine empirically for your "
                              "model first, see README 'Before the real run'")
    parser.add_argument("--max-new-tokens-cap", type=int, default=128,
                         help="clip real GeneratedTokens to this, since the tiny stand-in model has "
                              "no learned stopping behavior and do_sample rarely emits EOS early, so "
                              "every request runs its full requested length")
    parser.add_argument("--speed", type=float, default=1.0,
                         help="time-compression multiplier -- 2.0 replays twice as fast as the real trace")
    parser.add_argument("--concurrency", type=int, default=32,
                         help="max in-flight requests -- real peak concurrency in this trace can be "
                              "high, this caps how many the executor will run at once")
    parser.add_argument("--limit", type=int, default=None, help="only replay the first N rows (dry runs)")
    args = parser.parse_args()

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    prompt_bank = build_prompt_bank(tokenizer, args.max_context_tokens)

    rows = load_trace(args.trace_csv, args.limit)
    if not rows:
        raise SystemExit("no rows loaded from trace")
    t0 = rows[0]["timestamp"]
    log(f"loaded {len(rows)} real requests, real span "
        f"{(rows[-1]['timestamp'] - t0).total_seconds() / 60:.1f} min, "
        f"replaying at {args.speed}x")

    clipped_ctx = sum(1 for r in rows if r["context_tokens"] > args.max_context_tokens)
    clipped_gen = sum(1 for r in rows if r["generated_tokens"] > args.max_new_tokens_cap)
    log(f"{clipped_ctx}/{len(rows)} rows have ContextTokens above --max-context-tokens "
        f"({args.max_context_tokens}), {clipped_gen}/{len(rows)} have GeneratedTokens above "
        f"--max-new-tokens-cap ({args.max_new_tokens_cap}) -- both will be clipped")

    session = requests.Session()
    stats = {"sent": 0, "ok": 0}
    stats_lock = threading.Lock()
    start_wall = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for i, row in enumerate(rows):
            due_at = start_wall + (row["timestamp"] - t0).total_seconds() / args.speed
            sleep_for = due_at - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            context_tokens = min(row["context_tokens"], args.max_context_tokens)
            max_new_tokens = min(row["generated_tokens"], args.max_new_tokens_cap)
            pool.submit(
                fire, session, args.target, tokenizer, prompt_bank,
                context_tokens, max_new_tokens, stats, stats_lock,
            )
            if (i + 1) % 500 == 0:
                with stats_lock:
                    log(f"{i + 1}/{len(rows)} requests dispatched, "
                        f"{stats['sent']} completed ({stats['ok']} ok)")

    log("all requests dispatched, waiting for in-flight completions...")
    with stats_lock:
        log(f"final: {stats['sent']} completed, {stats['ok']} ok")


if __name__ == "__main__":
    main()
