# Right-sizing mini-test (RTX 3090 -> T4)

**Status: SCRIPTS DRY-RUN HERE (fake vLLM + fake nvidia-smi), NOT RUN ON REAL GPUs YET.**

Tests the product's riskiest unverified assumption for under ~$0.50: that a
workload's busy % times its GPU's FP16 TFLOPS is the compute it needs, so a
GPU with enough TFLOPS at a 70% ceiling can take it over. `ceiling.py` sizes
on TFLOPS only; LLM token generation is usually limited by memory speed.
RTX 3090 -> T4 is the sharpest case: 1.1x less compute, 2.9x less memory speed.

No Kubernetes and no product deployment: `compare.py` feeds the measured
peak into the product's real `ceiling.py` and checks the result.

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
