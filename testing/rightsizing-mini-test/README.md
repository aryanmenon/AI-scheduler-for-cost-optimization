# Right-sizing mini-test (RTX 3090 -> T4)

**Status: RUN 2026-10-04. RESULT: FAIL -- the product's sizing assumption
does not hold for LLM serving.** See `results/` (both result files and the
full `compare.py` output).

| | RTX 3090 (before) | T4 (after) | after/before |
|---|---|---|---|
| requests / errors | 237 / 0 | 237 / 0 | |
| latency p50 / p95 / p99 (s) | 1.91 / 2.21 / 2.38 | 4.44 / 5.16 / 5.61 | 2.3x |
| output tokens/s | 48.1 | 48.0 | 1.00x |
| mean busy % | 21.4 | 54.3 | 2.54x |
| peak busy %, 30 s sampling | 75 | 97 | |

- Product's assumption: busy % scales by the FP16 TFLOPS ratio (1.09x),
  predicting ~23% on the T4. Measured 54% (2.54x), close to the
  memory-speed ratio (2.92x). Latency rose 2.3x (pass bar 1.5x). Capacity
  held: same throughput, no queueing, no errors.
- The 3090's product-style peak was 71-75% at only ~0.26 req/s (GPU busy %
  reads high whenever any request is in flight), so the product's
  over-provisioned finding (peak <= 30%) would not fire for this service.
  At that peak `ceiling.py` would pick an L4 (300 GB/s, slower memory
  than the T4), which would very likely fail the same way.
- What went wrong during the run, for next time: vllm 0.8.5 needs
  `transformers<5` (pinned now); Colab ships Python 3.13, so the T4 side
  ran in a uv-made Python 3.12 venv (`pip install uv && uv venv --seed -p
  3.12 /content/v`, then run with `/content/v/bin/python`).

## Files
- `rightsize_minitest.py` -- one side: installs vllm 0.8.5.post1 if missing,
  serves Qwen2.5-1.5B-Instruct (fp16, V0 engine so it runs on a T4), replays
  the Azure conv trace with `../client-cluster-verification-test/trace_load.py`
  (must sit in the same directory), logs `nvidia-smi` every 1 s, prints
  `RESULT_JSON` and writes `result-<label>.json`. "Product-style peak" =
  max of samples taken every 30 s (the collector's scrape interval).
- `compare.py` -- `python3 compare.py result-before.json result-after.json`,
  run from a repo checkout (imports the product's capability table and
  ceiling.py). Same pass bars as verify.py: p95 <= 1.5x PASS, <= 2x
  MARGINAL; errors <= 0.5%; send lag p95 <= 5 s.

## Steps
1. "Before": vast.ai **Docker instance** (not VM), 1x RTX 3090, max CUDA
   >= 12.4, >= 40 GB disk, PyTorch template. Upload both scripts (`scp`;
   the repo is private, so no token on the box).
2. Calibrate: `python3 rightsize_minitest.py --label cal --minutes 5`.
   The product only flags over-provisioning when the peak is < 30%; aim for
   a product-style peak <= ~25%. If higher, lower `--keep-fraction`
   (default 0.05) and re-calibrate.
3. `python3 rightsize_minitest.py --label before --minutes 30 --stop-server`
   (`--gpu-mem 0.50` default = ~12 GB on 24 GB). Copy `result-before.json`
   off, then **destroy** the instance.
4. "After": free T4 on Colab or Kaggle. Upload both scripts, run
   `!python3 rightsize_minitest.py --label after --minutes 30 --gpu-mem 0.80
   --keep-fraction <same as before>` (0.80 of 15 GB = ~12 GB, same KV budget).
5. `compare.py` on the two result files.

## Known limits
- Two different hosts (vast.ai vs Google). Prompts are sent as token IDs, so
  host CPU barely matters; the pass bar is 1.5x.
- 30 minutes and one model, at light load; the product's real threshold
  needs 24 h of observation. This tests the sizing logic, not detection.
- The RTX 3090 is a consumer card (known to the product, never recommended);
  it proves the logic, not a realistic client setup.
