# Real inference-traffic replay (Azure LLM Inference Trace 2023)

A different kind of real-world validation than `testing/real-trace-replay`
(the Philly replay). That test replayed already-recorded real *utilization*
numbers entirely offline -- no GPU needed, but it also carries the caveat
that Philly is 2017 *training* workloads, not the bursty small-batch
*inference* traffic this product actually targets.

This test instead replays a real 2023 *inference request-arrival* trace
against a real GPU-backed inference server, so the utilization it produces
is genuinely caused by real request timing and real request sizes -- not
`load_generator.py`'s own randomized burst/quiet cycles, and not 2017
training-era behavior. The tradeoff: unlike the Philly replay, this needs a
real rented GPU and runs in real (or `--speed`-multiplied) time, following
the same live-infrastructure pattern as the fragmentation and
heterogeneous-SKU tests.

## Data source

[`AzureLLMInferenceDataset2023`](https://github.com/Azure/AzurePublicDataset/blob/master/AzureLLMInferenceDataset2023.md)
-- real LLM inference request traces from Azure's own production services,
collected in November 2023, released alongside
["Splitwise: Efficient Generative LLM Inference Using Phase Splitting"](https://www.microsoft.com/en-us/research/publication/splitwise-efficient-generative-llm-inference-using-phase-splitting/)
(ISCA 2024). CC-BY licensed; cite the paper if this data is used further.

Two files, two distinct real workload types:

| File | Real requests | Real span | ContextTokens (median / p95 / max) | GeneratedTokens (median / p95 / max) |
|---|---|---|---|---|
| `AzureLLMInferenceTrace_conv.csv` (conversational) | 19,366 | ~58 min | 1020 / 4083 / 14050 | 129 / 451 / 1000 |
| `AzureLLMInferenceTrace_code.csv` (code completion) | 8,819 | ~59 min | 1469 / 7315 / 7437 | 13 / 90 / 1899 |

Each row is `TIMESTAMP,ContextTokens,GeneratedTokens` -- real invocation
time and real input/output token counts. **Prompt text itself is not
included** (Microsoft stripped it for privacy) -- only token counts, so
this replay reconstructs a prompt of the *real* token length rather than
using the real text.

Verified downloadable (checked live, HTTP 200, both fetch via GitHub's raw
CDN, no LFS pointer issue this time unlike Philly):
```bash
mkdir -p /tmp/azure-trace && cd /tmp/azure-trace
curl -sSL -o conv.csv "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/AzureLLMInferenceTrace_conv.csv"
curl -sSL -o code.csv "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/AzureLLMInferenceTrace_code.csv"
```

## Design decisions and caveats

- **Real pass, not a re-proof of duration thresholds.** Real span is only
  ~58 minutes per file -- not enough for real (non-smoke-test) idle
  (4h+) or over-provisioned (24h+) thresholds. This test uses
  `values-smoke-test.yaml` (1h streaks) for the same reason the
  heterogeneous-SKU test did: it targets a different question (does
  detection work on genuinely real *request-driven* utilization) than
  duration/threshold re-proof, already settled by test 1.
- **Real inter-arrival timing is preserved exactly** (down to the
  microsecond, `--speed 1.0` by default) -- this is the actual point:
  real request bursts and real gaps, not a randomized schedule.
- **Real relative token-size distribution is preserved; absolute values
  are clipped** to whatever the serving model can actually handle.
  `sshleifer/tiny-gpt2` (this project's existing stand-in model, same one
  `fragmentation-and-load-test/server.py` already uses) was NOT verified
  in this sandbox to have a specific max context length -- huggingface.co
  is unreachable from here. **Determine the real number empirically on the
  rented GPU box itself before the real run** (see below) rather than
  trusting a guessed value -- passing a wrong `--max-context-tokens` either
  wastes real GPU-hours erroring on every request, or silently clips more
  of the real trace than necessary.
- **Prompt reconstruction, not real prompt replay.** Since real prompt
  text isn't in the dataset, prompts are built by slicing a filler passage
  to the exact real token count using the serving model's own tokenizer.
  This preserves real per-request compute proportionality (a 4000-token
  real request still costs roughly 4000 tokens of real compute) without
  claiming to reproduce the real conversation content.

## Before the real run: determine `--max-context-tokens`

On the rented GPU box, after `server.py` is up, find the model's real
practical limit with an increasing test request rather than guessing:
```bash
python3 -c "
import requests
for n in [512, 1024, 2048, 4096]:
    prompt = ('word ' * n).strip()
    r = requests.post('http://localhost:8000/generate', json={'prompt': prompt, 'max_new_tokens': 1}, timeout=30)
    print(n, r.status_code, r.text[:200])
"
```
Use the largest `n` that returns 200 as `--max-context-tokens`. Every real
`ContextTokens` value above that gets clipped to it (the script logs
exactly how many rows that affects up front -- check that number isn't
close to 100% before committing to a multi-hour real run).

## 1. Reuse the existing single-GPU inference server setup

**Correction from an earlier draft of this README:** the inference server
MUST run as a real Kubernetes pod requesting `nvidia.com/gpu`, not as a
bare `docker run` outside Kubernetes. `correlator.py`/`normalizer.py`
filter out any GPU sample that doesn't carry a real pod/namespace label
(`UNATTRIBUTED`) *before* any detector ever sees it -- exactly the
mechanism debugged live during the GKE test. A bare `docker run` container
is invisible to DCGM's Kubernetes pod-attribution, so every sample would
be filtered out and no finding would ever fire -- silently wasting the
whole rental. This test still needs the fragmentation test's base
single-node k3s setup (just one node/one GPU, no second node needed --
that was specific to the heterogeneous-SKU test's cross-SKU requirement):

```bash
cd testing/fragmentation-and-load-test
docker build -t tiny-model-server:test .
# k3s ctr images import, then deploy as a real k8s Deployment+Service
# requesting nvidia.com/gpu -- reuse k8s/workload-a.yaml as a template
# (single workload only, no workload-b needed), exactly like that test's
# README section 1-4 describes for a single-GPU rental.
```
Deploy the product's telemetry chart pointed at that same k3s cluster with
`values-smoke-test.yaml`, same as every other live test in this project.

## 2. Determine `--max-context-tokens` (see above), then run the replay

Run this ON the rented VM itself (via SSH), not through an intermediary
like Cloud Shell -- the GKE test's load generator got silently truncated
twice by an unrelated Cloud Shell VM restart, and this run can be up to
~58 real minutes. Use `tmux`/`screen` on the VM so an SSH drop doesn't
kill it either:
```bash
tmux new -s replay
kubectl -n inference port-forward svc/tiny-model 8001:8000 &

pip install requests transformers

python3 replay_request_trace.py /tmp/azure-trace/conv.csv \
  --target http://localhost:8001/generate \
  --max-context-tokens <determined above> \
  --max-new-tokens-cap 128 \
  --speed 1.0
# Ctrl+B D to detach the tmux session if you need to disconnect;
# `tmux attach -t replay` to come back to it.
```
`--max-new-tokens-cap` defaults to 128 regardless of the real
`GeneratedTokens` value's max (up to 1899 in this data) because the stand-in
model has no learned stopping behavior -- `do_sample=True` on a randomly
weighted tiny model essentially never emits its own EOS token early, so it
always generates the full requested length. Requesting the real p95/max
values verbatim would make a meaningful fraction of requests take
disproportionately long for no detection-relevant reason. Real relative
sizing (some requests bigger than others) is preserved either way; only
the absolute ceiling is capped for practicality.

Runs in real time by default -- the ~58-minute real span takes ~58 real
minutes. Use `--speed 4` or higher to compress it if a shorter run is
acceptable (bursty timing patterns are preserved either way, just
compressed).

Run `conv.csv` and `code.csv` as two separate passes (or two concurrent
processes against the same server, if testing fragmentation-style
same-node contention between the two real workload types is of interest).

## 3. What to check

Same finding-check query as the other tests:
```bash
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c waste-detector -- python3 -c "
import sqlite3
conn = sqlite3.connect('/data/findings/findings.db')
cur = conn.cursor()
cur.execute('SELECT category, node, gpu_index, workload, metric_value FROM waste_findings ORDER BY id DESC')
for row in cur.fetchall(): print(row)
"
```

The real question this test answers: does a genuinely real, bursty,
inference-shaped request pattern -- not a synthetic randomized one, not a
2017 training workload -- produce utilization data the actual detector
correctly interprets? Given the real trace's median utilization-driving
request is fairly small (median ContextTokens ~1000-1500, median
GeneratedTokens 13-129), expect `idle` and/or `over_provisioned` findings
during real quiet gaps between the trace's own natural bursts, similar in
character to the fragmentation test's over-provisioned finding but driven
by genuinely real inference request timing this time.
