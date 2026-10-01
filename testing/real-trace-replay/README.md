# Real-trace replay: does the detector work on real waste patterns?

Every other test kit in `testing/` proves the pipeline works end-to-end on
*real infrastructure* (real GPUs, real k8s, real DCGM) -- but every
utilization pattern fed into them was synthetic, written by this project's
own load generators, tuned to be detectable. This test instead answers a
different question: does the detection *logic* correctly identify waste in
genuinely real-world usage data, not just the patterns we designed
ourselves to trigger it?

No live cluster needed for this one -- it's pure offline data replay
against the actual `waste_detector` code, using its real hourly-rollup
thresholds (not the lowered `values-smoke-test.yaml` ones).

## Data source

[msr-fiddle/philly-traces](https://github.com/msr-fiddle/philly-traces) --
a real, sanitized subset of Microsoft's internal Philly GPU cluster
(552 machines, 117,325 real training jobs, August-December 2017), released
alongside ["Analysis of Large-Scale Multi-Tenant GPU Clusters for DNN
Training Workloads"](https://arxiv.org/abs/1901.05758) (ATC'19). If you use
this trace, cite that paper (see the source repo's own request).

Two Alibaba `clusterdata` releases were considered first and ruled out:
`cluster-trace-gpu-v2023` (the "Beware of Fragmentation" trace) turned out
to be pure job-scheduling/allocation data with **no utilization
measurements at all**; `cluster-trace-gpu-v2020`'s `pai_sensor_table` only
has one aggregate avg/max utilization figure per job's *entire* lifetime,
not a real per-interval time series. Neither can exercise this detector's
streak/contiguity/hour-of-day logic. Philly's `cluster_gpu_util` is a
genuine **per-minute, per-GPU-slot** utilization series (real `nvidia-smi`
readings), which is what this test actually needs.

## Getting the data

The archive (`trace-data.tar.gz`, ~1GB compressed / 6.6GB extracted) is
Git-LFS-tracked in the source repo. A plain `git clone` only fetches the
135-byte LFS pointer, not the real file. Fetch the real content via
GitHub's LFS media-resolving CDN instead:

```bash
mkdir -p /tmp/philly-trace && cd /tmp/philly-trace
curl -sSL -o trace-data.tar.gz \
  "https://media.githubusercontent.com/media/msr-fiddle/philly-traces/master/trace-data.tar.gz"
# verify against the LFS pointer's oid before trusting it:
#   git show HEAD:trace-data.tar.gz   (in a clone of the source repo)
sha256sum trace-data.tar.gz   # expect 2037ccf63a725a02be718b0e1aeee6142c90b7f62d0d849295120e9f6ba13d2c
tar -xzf trace-data.tar.gz    # -> trace-data/cluster_gpu_util, cluster_job_log, etc.
```

## Running it

```bash
python3 replay.py /tmp/philly-trace/trace-data [output_dir]
python3 summarize.py [output_dir]/findings.pkl

# After changing a detector: re-run on the rollups replay.py saved, no
# re-download or re-read of the 6.6GB trace needed (seconds, not ~10 min).
python3 rerun_detectors.py [output_dir]
python3 summarize.py [output_dir]/findings.pkl
```

`replay.py` streams the full 44.75M-row `cluster_gpu_util` (only ~10 min on
a 4-core/15GB box), attributes each real per-minute reading to the real
job that really occupied that GPU slot at that time (via
`cluster_job_log`'s scheduling intervals), buckets into real hourly rollups
matching `ingestion_normalization.rollup`'s schema (saved as
`rollups.pkl`), and runs the actual waste_detector functions (idle,
over-provisioning, fragmentation, recurring patterns, multi-GPU oversized)
against them -- the identical code path the live product uses, just fed
real historical data instead of a live DCGM scrape.

Window: a real 31-day slice, 2017-10-03 through 2017-11-02 (entirely one
DST regime, avoiding the Nov 5 fall-back ambiguous-hour edge case; long
enough to satisfy every detector's minimum evidence bar, including
recurring-pattern's 7+ distinct calendar days).

## Results (current detectors, 2026-10-01)

Real pilot thresholds (not smoke-test lowered ones), full 31-day window,
44,750,640 total CSV rows read, 18,877,380 in-window, 85,614,120 real
attributed GPU-minute readings, 1,538,668 hourly rollup rows built:

| Category | Findings |
|---|---|
| Idle | 10,990 |
| Over-provisioned | 279 |
| Fragmented | 5,718 |
| Recurring pattern | 6,848 |
| Multi-GPU oversized (visibility only) | 24,570 |
| Underutilized, no recommendation | 58,491 |
| Unattributed GPU time, no recommendation | 0 (the replay only builds rows for GPU time attributed to a job) |

**16.7% of observed GPU-workload-hours were flagged as actionable waste**
(`summarize.py`'s merged-interval union across idle, over-provisioned,
fragmented and recurring-pattern, so an hour double-flagged only counts
once). **14.7%** counting only idle, over-provisioned and recurring-pattern
findings -- the floor, since fragmentation findings are unverified
consolidation candidates (memory fit, combined compute and GPU sharing
aren't checked).

**Separately, not part of the 16.7%:** multi-GPU jobs that may be able to
run on fewer GPUs account for **12.7%** of GPU-hours as releasable capacity
(**7.0%** not already flagged above). That's an upper bound sized on hourly
averages with no memory check -- see `waste_detector/multi_gpu.py`.

**Also separate: detected waste with no recommendation.** Every other
GPU-hour averaging below the 70% efficient-use target that no finding
explains: **13.4%** of GPU-hours, amounting to **2.5%** of total GPU
capacity unused below the target (mostly short stretches -- median 1h,
average shortfall ~19% of a GPU). Together, findings in some tier touch
57.3% of GPU-hours; that's a coverage figure, not an amount of waste (a
multi-GPU finding touches every GPU of a job even though only a fraction
is releasable). The rest is hours at or above 70% (not waste by this
definition) or low-coverage hours the detectors deliberately skip.

### How the headline figure changed

| Run | Flagged | What changed |
|---|---|---|
| 2026-09-27 | 23.0% | Original run |
| 2026-10-01 (a) | 17.1% | Fragmentation stopped flagging multi-GPU jobs (consolidating them onto a shared GPU is impossible). Of the 6.3 points that dropped out, 60% were multi-GPU jobs' GPU-hours and 40% were single-GPU workloads that had only qualified because a multi-GPU job sat next to them |
| 2026-10-01 (b) | 16.7% | Fragmentation findings split per GPU *and* workload: a GPU that switched jobs mid-streak had been charging the first job for every hour (6,419 GPU-hours misattributed) |

Idle, over-provisioned and recurring-pattern counts are identical across
all three runs. Raw output for each is in `RESULTS.md`. This is the first
real evidence-backed answer to "will this detector reliably find real
waste" -- previously only a synthetic-data claim.

## What this does and does not prove

**Does prove**: the detection logic (streak/contiguity math, coverage
gating, threshold comparisons, hour-of-day pattern matching) correctly
identifies waste in genuinely real, messy, multi-tenant production
scheduling data -- not just the clean synthetic pattern this project's own
load generators were built to trigger.

**Does not prove**:
- **Workload shape match**: Philly is 2017 *training* workloads, not the
  bursty small-batch *inference* traffic this product's `idle.py` docstring
  says it's tuned for. A training job's utilization shape is different
  (often long steady runs vs. inference's frequent short bursts).
- **The GPU_UTIL-as-FLOPS-proxy gap** (see `PROGRESS.md` section 6) applies
  here identically -- Philly's `gpu_util` is the same NVIDIA-defined
  time-occupancy metric, not a throughput measure. This replay validates
  the *detection* logic, not the *right-sizing recommendation* math in
  `ceiling.py` (which this replay doesn't price at all, since Philly-era
  K80/P100 GPUs aren't in `capability.py`'s table and pricing wasn't the
  point of this exercise).
- **Not the 30-40% utilization-gain business thesis** -- that can only be
  validated against a real customer's real organic traffic, never a
  self-run test on someone else's historical data, however real.
