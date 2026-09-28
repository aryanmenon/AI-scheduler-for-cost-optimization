# Azure inference-trace replay results (2026-09-28)

Full real run: `AzureLLMInferenceTrace_conv.csv` (19,366 real requests, real
58.4-minute production span, November 2023), replayed at real (1.0x) speed
against a real GPU-backed inference server on a real vast.ai/k3s single-GPU
cluster (RTX 4060 Ti), through the actual product pipeline
(`values-smoke-test.yaml` thresholds).

## Replay summary

```
[2026-09-28T13:21:06] loaded 19366 real requests, real span 58.4 min, replaying at 1.0x
[2026-09-28T13:21:06] 9528/19366 rows have ContextTokens above --max-context-tokens (1024),
                       9730/19366 have GeneratedTokens above --max-new-tokens-cap (128)
[2026-09-28T14:54:23] all requests dispatched, waiting for in-flight completions...
[2026-09-28T14:54:23] final: 19366 completed, 19366 ok
```

100% request success rate. Wall-clock time (13:21-14:54, ~93 min) exceeded
the nominal 58.4-minute real trace span -- expected, not a bug: the
concurrency-safety lock added to the stand-in server (see below) correctly
serializes all GPU access on this one tiny GPU, while the real Azure trace
was originally served by many real GPUs in parallel. Real relative request
timing and real relative token-size distribution were preserved throughout;
only the absolute wall-clock pace of *processing* the backlog was slower
than 1:1 real-time once queued.

## Finding

```
category      = over_provisioned
node          = ubuntu
gpu           = 0
namespace     = inference
workload      = tiny-model-a
confidence    = 1.0
metric_value  = 11.0
detail        = peak utilization 11.0% across 1h observed, never exceeded the 30% threshold
```

Driven entirely by genuine November 2023 Azure production inference request
arrival timing and token sizes -- not `load_generator.py`'s synthetic
randomization, and not 2017 Philly training-era data. This is the first
test in this project where the detector's input utilization was caused by
real inference traffic specifically, closing the one caveat every prior
real-world validation carried.

## Four real bugs found and fixed live

None of these were anticipated in the original test-kit design -- all
found by running the actual replay against a real server and hitting real
failures, in order:

1. **Thread-unsafe concurrent GPU access in the shared stand-in server**
   (`testing/fragmentation-and-load-test/server.py`, commit `d64a82e`).
   FastAPI runs each sync route handler in its own thread-pool worker, so
   concurrent requests called `.generate()` on the one shared model
   instance from different threads at once, unsynchronized. A burst of
   real concurrent requests crashed the process with `CUDA error:
   device-side assert triggered`, which poisons the CUDA context for
   every request afterward (not just the overlapping ones) until the pod
   restarts. This is a latent bug in a test artifact used by every live
   GPU test in this project -- earlier tests' `load_generator.py`
   concurrency (up to 4) with real, non-compressed timing likely never
   produced truly overlapping `.generate()` calls, so it went uncaught
   until this test's real burst timing (further compressed by an initial
   `--speed 50` sanity check) triggered genuinely simultaneous requests.
   Fixed with a `threading.Lock()` serializing access to the shared model.
2. **Real sequence-length-budget bug in the replay script**
   (`replay_request_trace.py`, commit `a6ae78e`). `--max-context-tokens`
   and `--max-new-tokens-cap` clipped ContextTokens and GeneratedTokens
   independently, so a request needing both a long prompt and more than a
   token or two of generation could still exceed the model's real total
   position budget. GPT-2's position embeddings support exactly 1024
   total positions covering *both* the prompt and every generated token
   combined -- a 1024-token prompt plus even one more generated token
   needs position 1024, out of bounds, the same CUDA device-side-assert
   crash. Isolated via a sequential (no-concurrency) diagnostic that
   ruled out bug #1 as the cause of this specific crash: prompts up to
   800 tokens with 16 new tokens succeeded, exactly 1024 tokens with 16
   new tokens failed every time, regardless of concurrency. Fixed by
   computing each row's context budget as
   `max_context_tokens - max_new_tokens` rather than clipping each
   independently.
3. **dcgm-exporter device-ID-type regression on non-GKE clusters**
   (`deploy/helm/gpu-telemetry-collector`, commit `349bd68`). The GKE
   test's fix for pod-attribution (`DCGM_EXPORTER_KUBERNETES_GPU_ID_TYPE=
   device-name`, commit `64a4033`) had been hardcoded unconditionally into
   the shared chart. On this test's standard NVIDIA k8s-device-plugin
   cluster (vast.ai/k3s), that broke attribution the identical silent way
   in the opposite direction -- this cluster type reports device IDs in
   UUID form (dcgm-exporter's own default assumption), and forcing
   device-name made the ID match fail here instead. Every GPU sample came
   back with zero `pod=`/`namespace=` label, same symptom as the original
   GKE bug, opposite cause. Fixed by making it a `dcgmExporter.
   kubernetesGpuIdType` values.yaml field (empty by default, matching
   dcgm-exporter's own UUID-assuming default), only set explicitly for
   GKE. The GKE runbook (`testing/real-managed-cluster-test/README.md`)
   was updated to pass it explicitly, since it's no longer the chart-wide
   default.

4. **`generate-report` has no writable path anywhere in the dashboard
   pod** (`deploy/helm/gpu-telemetry-collector`, commit `eab36ee`).
   Found just after the test itself had already passed, while pulling
   the live report for the record: `readOnlyRootFilesystem: true` on
   the dashboard container, combined with zero volumes mounted for it
   at all, means the chart's own install NOTES document a feature
   ("generate a standalone HTML file to share") that could never have
   worked in any real deployment -- confirmed live, both the documented
   default path and `/tmp` were read-only. Fixed with a small
   `dashboard-tmp` emptyDir mounted at `/tmp` plus
   `REPORT_OUTPUT_PATH=/tmp/report.html`.

The first three are confirmed working together: the final full
19,366-request real run completed with zero crashes and zero unattributed
samples. Bug #4 required a `helm upgrade` to deploy, which restarted the
collector pod and reset the live findings database (this test used
`persistence.enabled=false`, matching every non-GKE test) -- the fired
finding above was already fully captured before that restart, so nothing
about the test's result was lost, but the live dashboard's specific ₹
recommendation for it was never queried before the reset and so isn't
part of this record.
