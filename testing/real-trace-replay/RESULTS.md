# Real-trace replay results

Full stdout from `replay.py` + `summarize.py` on the 2017-10-03 through 2017-11-02 window.

```
[12:33:17] loading job_log ...
[12:33:18] 117325 jobs loaded
[12:33:20] built interval index: 2308 (machine,gpu) keys, 164361 intervals (136 attempts skipped for unparseable timestamps)
[12:33:56] 5.0M rows read (36s elapsed, 2139047 in-window, 7480297 attributed)
[12:34:40] 10.0M rows read (79s elapsed, 4260814 in-window, 19036276 attributed)
[12:35:15] 15.0M rows read (115s elapsed, 6345141 in-window, 26543268 attributed)
[12:35:59] 20.0M rows read (159s elapsed, 8469788 in-window, 37160360 attributed)
[12:36:42] 25.0M rows read (201s elapsed, 10565635 in-window, 47536862 attributed)
[12:37:25] 30.0M rows read (244s elapsed, 12664362 in-window, 57912473 attributed)
[12:38:02] 35.0M rows read (282s elapsed, 14794215 in-window, 66644165 attributed)
[12:38:46] 40.0M rows read (326s elapsed, 16896376 in-window, 77318055 attributed)
[12:39:22] done reading: 44750640 total rows, 18877380 in-window, 85614120 attributed GPU-minute readings, 1538668 distinct hourly-bucket groups (361s)
[12:39:35] 1538668 hourly rollup rows built, running detectors ...

======================================================================
RESULTS: real waste-detector code run against real Philly production data
======================================================================
idle findings:            10990
over-provisioned findings: 279
fragmented findings:       12568
recurring-pattern findings:6848

--- IDLE (showing up to 5 of 10990) ---
  node=m29 gpu=0 ns=7f04ca workload=application_1506638472019_2368 confidence=1.00 metric=4.00 :: idle (avg and max utilization <= 2%) for 4 consecutive hours with no bursts observed
  node=m29 gpu=1 ns=7f04ca workload=application_1506638472019_2368 confidence=1.00 metric=4.00 :: idle (avg and max utilization <= 2%) for 4 consecutive hours with no bursts observed
  node=m29 gpu=2 ns=7f04ca workload=application_1506638472019_2368 confidence=1.00 metric=4.00 :: idle (avg and max utilization <= 2%) for 4 consecutive hours with no bursts observed
  node=m29 gpu=3 ns=7f04ca workload=application_1506638472019_2368 confidence=1.00 metric=4.00 :: idle (avg and max utilization <= 2%) for 4 consecutive hours with no bursts observed
  node=m29 gpu=4 ns=7f04ca workload=application_1506638472019_2368 confidence=1.00 metric=4.00 :: idle (avg and max utilization <= 2%) for 4 consecutive hours with no bursts observed

--- OVER_PROVISIONED (showing up to 5 of 279) ---
  node=m313 gpu=4 ns=6214e9 workload=application_1504131676014_12811 confidence=1.00 metric=0.00 :: peak utilization 0.0% across 161h observed, never exceeded the 30% threshold
  node=m313 gpu=7 ns=6c71a0 workload=application_1506638472019_8056 confidence=1.00 metric=27.00 :: peak utilization 27.0% across 27h observed, never exceeded the 30% threshold
  node=m313 gpu=5 ns=6c71a0 workload=application_1506638472019_8121 confidence=1.00 metric=26.80 :: peak utilization 26.8% across 27h observed, never exceeded the 30% threshold
  node=m313 gpu=4 ns=6c71a0 workload=application_1506638472019_23541 confidence=1.00 metric=29.60 :: peak utilization 29.6% across 34h observed, never exceeded the 30% threshold
  node=m257 gpu=0 ns=6c71a0 workload=application_1508364558011_13082 confidence=1.00 metric=0.00 :: peak utilization 0.0% across 28h observed, never exceeded the 30% threshold

--- FRAGMENTED (showing up to 5 of 12568) ---
  node=m310 gpu=0 ns=6c71a0 workload=application_1506638472019_7926 confidence=1.00 metric=3.00 :: node m310 had an average of 3.0 GPUs (< 50% utilized) from 3.0 distinct workloads simultaneously idle-ish for 22h -- consider consolidating
  node=m310 gpu=5 ns=6c71a0 workload=application_1506638472019_7918 confidence=1.00 metric=3.00 :: node m310 had an average of 3.0 GPUs (< 50% utilized) from 3.0 distinct workloads simultaneously idle-ish for 22h -- consider consolidating
  node=m310 gpu=6 ns=6c71a0 workload=application_1506638472019_7927 confidence=1.00 metric=3.00 :: node m310 had an average of 3.0 GPUs (< 50% utilized) from 3.0 distinct workloads simultaneously idle-ish for 22h -- consider consolidating
  node=m310 gpu=1 ns=6214e9 workload=application_1506638472019_14926 confidence=0.99 metric=7.42 :: node m310 had an average of 7.4 GPUs (< 50% utilized) from 2.3 distinct workloads simultaneously idle-ish for 24h -- consider consolidating
  node=m310 gpu=2 ns=6214e9 workload=application_1506638472019_15188 confidence=0.99 metric=7.42 :: node m310 had an average of 7.4 GPUs (< 50% utilized) from 2.3 distinct workloads simultaneously idle-ish for 24h -- consider consolidating

--- RECURRING_PATTERN (showing up to 5 of 6848) ---
  node=m29 gpu=0 ns=b436b2 workload=application_1508364558011_18916 confidence=1.00 metric=0.86 :: utilization <= 5% at 20:00 UTC on 6/7 observed days -- recurring low-usage window
  node=m29 gpu=1 ns=b436b2 workload=application_1508364558011_18916 confidence=1.00 metric=0.86 :: utilization <= 5% at 20:00 UTC on 6/7 observed days -- recurring low-usage window
  node=m29 gpu=2 ns=b436b2 workload=application_1508364558011_18916 confidence=1.00 metric=0.86 :: utilization <= 5% at 20:00 UTC on 6/7 observed days -- recurring low-usage window
  node=m29 gpu=3 ns=b436b2 workload=application_1508364558011_18916 confidence=1.00 metric=0.86 :: utilization <= 5% at 20:00 UTC on 6/7 observed days -- recurring low-usage window
  node=m29 gpu=5 ns=b436b2 workload=application_1508364558011_18916 confidence=1.00 metric=0.86 :: utilization <= 5% at 20:00 UTC on 6/7 observed days -- recurring low-usage window

[12:39:44] saved raw findings to findings.pkl

total observed GPU-workload-hours (rollup rows): 1538668
distinct (node,gpu,ns,workload) keys with >=1 finding: 15277
total flagged hours (merged, no double-counting overlap): 353955
fraction of observed capacity-hours flagged as some form of waste: 23.0%
```

## Re-run 2026-10-01: corrected fragmentation detector

Same trace, same 2017-10-03 to 2017-11-02 window, same thresholds. Only
change: `waste_detector/fragmentation.py` now excludes any workload holding
more than one GPU in an hour (multi-GPU training/inference can't be
consolidated onto a shared GPU). The run above predates that fix and its
23.0% figure is superseded.

```
idle findings:            10990
over-provisioned findings: 279
fragmented findings:       4636     (was 12568)
recurring-pattern findings:6848

total observed GPU-workload-hours (rollup rows): 1538668
distinct (node,gpu,ns,workload) keys with >=1 finding: 12282
total flagged hours (merged, no double-counting overlap): 263667
fraction of observed capacity-hours flagged as some form of waste: 17.1%

excluding fragmentation findings (idle + over-provisioned + recurring only):
fraction of observed capacity-hours flagged as some form of waste: 14.7%
```

Idle, over-provisioned and recurring-pattern counts are identical to the
first run, as expected: the fix only touched the fragmentation detector.

## Re-run 2026-10-01 (b): mislabel fix + multi-GPU visibility signal

Same rollups (saved by `replay.py`, re-run with `rerun_detectors.py`), same
thresholds. Changes: fragmentation findings keyed per GPU *and* workload
(a GPU that switched jobs mid-streak had been charging the first job for
every hour), and the new visibility-only `multi_gpu_oversized` category.

```
idle findings: 10990
over_provisioned findings: 279
fragmented findings: 5718      (more findings, fewer hours: split per workload)
recurring_pattern findings: 6848
multi_gpu_oversized findings: 24570

total observed GPU-workload-hours (rollup rows): 1538668
distinct (node,gpu,ns,workload) keys with >=1 finding: 13220
total flagged hours (merged, no double-counting overlap): 256290
fraction of observed capacity-hours flagged as some form of waste: 16.7%
multi-GPU oversized findings (visibility only, NOT in the figure above): 24570
  releasable GPU-hours (upper bound): 194735 (12.7%), of which not already flagged above: 106952 (7.0%)
```

Example multi-GPU finding detail:

```
multi-GPU job held 8.0 GPUs on average for 119h with combined hourly-average busy
time of 373% of one GPU -- could likely release at least 1 GPU(s) and keep each
remaining GPU under 70% on hourly average. Upper bound for review, not a verified
recommendation: sized on hourly averages, so bursts may exceed that ceiling on fewer
GPUs; GPU memory fit not checked; GPU utilization is busy time, not compute used; for
training, fewer GPUs changes batch size and run time, and a data-loading or
communication bottleneck may be the cheaper fix
```

## Analysis 2026-10-01: where the 23.0% -> 17.1% drop came from

Old (pre-fix) and new fragmentation detectors run side by side on the same
rollups, flagged hours compared as sets of (GPU, workload, hour):

```
dropped hours 96707 (6.3 pts): from multi-GPU workloads 58271 (60%),
  from single-GPU workloads that lost their partner 38436 (40%)
usable GPU-hours 1386261: multi-GPU 1131562 (82%), single-GPU 254699
median hourly avg GPU_UTIL: single 54.3%  multi 53.6%
multi-GPU GPU-hours with avg 2-50% not flagged by anything: 341304 (22.2% of all GPU-hours)
```

Sizing the multi-GPU signal was prototyped two ways before building it
(GPUs needed = ceil(summed hourly utilization / 70%), 4h+ streak):

```
peak-based (hourly max per GPU):     +0.4 pts of GPU-hours -> 17.5% total
average-based (hourly avg per GPU):  +6.6 pts of GPU-hours -> 23.7% total
```

Peak-based found almost nothing because a job's busiest minute in an hour
is usually high; average-based was chosen and is shown separately as a
visibility-only upper bound rather than added to the headline.

