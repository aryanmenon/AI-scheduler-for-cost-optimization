# Real-trace replay results (2026-09-27)

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
