# Pilot install rehearsal

**Status: RUN 2026-10-04/05 -- ALL SIX CHECKS PASS; found and fixed one real bug (PR #7).**

Runs the published, Cython-compiled images (commit `eac69a9`, PR #6) on a
live GPU cluster, installed exactly the way a pilot customer will:
packaged chart `.tgz`, the pilot machine account's `read:packages` token
in a pull secret, and the commands in `docs/pilot/PILOT_GUIDE.md`.

Proves, in order:
1. A pilot can pull the private compiled images with the bot token.
2. All five compiled services start and run (`cycle_complete` log lines).
3. The running images contain no Python source.
4. The PersistentVolumeClaim binds.
5. A real idle GPU becomes an `idle` finding with a ₹ figure in the report.
6. Uninstall leaves nothing behind (no namespace, ClusterRole or PVC).

Cost: one cheap GPU on a vast.ai **Linux Virtual Machine** for ~2 hours
(an idle finding needs one full clock hour of data).

Files (send to the VM with `scp`): `gpu-telemetry-collector-0.4.0.tgz`
(`helm package deploy/helm/gpu-telemetry-collector`), `values-rehearsal.yaml`,
`idle-gpu-pod.yaml`. Cluster setup is the same k3s recipe as
`testing/client-cluster-verification-test/README.md` section 1, with the
NVIDIA device plugin pinned to v0.17.1.

## Results (2026-10-04 21:40 -> 2026-10-05 00:25 UTC)

Setup: vast.ai Ubuntu 22.04 VM, 1x RTX 3090 (India, $0.226/hr), k3s
v1.36.5+k3s1, NVIDIA device plugin v0.17.1, Helm v3.22.0. Installed exactly
as PILOT_GUIDE.md says: namespace + `ghcr-secret` from a classic
`read:packages` token typed at a hidden prompt, `rates.yaml` with a
"customer" rate of `{"NVIDIA GeForce RTX 3090": 20}` (~ the real rental
rate in Rs), `helm install gpu-optimizer <tgz> -f values-rehearsal.yaml -f rates.yaml`.

| # | Check | Result |
|---|---|---|
| 1 | Pull the private compiled images with the token | **PASS** -- all 5 pulled; pod 5/5 Running in 65 s |
| 2 | Compiled services run | **PASS** -- `cycle_complete`, `errors: 0`; no crash in 107 min |
| 3 | No source in the running images | **PASS** -- per container: telemetry_collector 6, ingestion_normalization 9, waste_detector 13, savings_estimator 10, dashboard 7 compiled modules; `source files: 0` everywhere; `__init__.py` = version only; no `/src` |
| 4 | PVC binds | **PASS** -- 5Gi `local-path` Bound |
| 5 | Idle GPU -> Rs finding in the report | **PASS** -- report fetched with the bearer token via port-forward: "Idle GPUs: idle-notebook / rehearsal / ubuntu gpu0 / 2026-10-04 23:00 UTC (1.0h) / **Rs20.00** / 1.0h idle at Rs20.00/hr (customer_provided_rate)" |
| 6 | Uninstall leaves nothing | **PASS** -- `helm uninstall` + `kubectl delete namespace`: no resources, namespaces, ClusterRole/Binding, PV or local-path data dir left; cached product images on the node 10 -> 0 with `crictl rmi` |

Also proven, unplanned:
- **Survives a node reboot**: all pods came back by themselves (one
  restart per container), PVC and data intact.
- **Mid-pilot upgrade**: `helm upgrade` to the PR #7 images (merge commit
  `eb0c958`) rolled the pod in < 2 min; the dashboard token carried over
  (`helm.sh/resource-policy: keep`); the on-volume schema migration ran
  (old index dropped, new one created, 23:00 data intact).

### Bug found and fixed: rollups failed whenever a GPU changed pod mid-hour

The rollups table's unique index was per GPU per bucket, but rollups are
one row per workload. When the GPU went from "no pod" to `idle-notebook`
at 22:27, every recompute of that hour (and of the day) raised
`sqlite3.IntegrityError: UNIQUE constraint failed: index 'uq_rollup_bucket'`
-- **370 ingestion errors** by 00:15, and the 22:00 hour kept only its
pre-switch row. On a real cluster that is nearly every hour (any job
start/stop). Fixed in PR #7 (index keyed by namespace + workload, old
index dropped on existing volumes, regression tests). Verified live after
the upgrade: replacing `idle-notebook` with `second-notebook` at 00:19
stored both rows for the 00:00 hour, `errors since upgrade: 0`. Hours lost
before the upgrade are not backfilled (only touched buckets are
recomputed) -- irrelevant before the first pilot.

### Environment issue (not the product): automatic driver upgrade

Minutes after boot Ubuntu's automatic upgrade replaced the NVIDIA driver
(580.95 -> 580.178) under the running kernel module; every new GPU pod then
failed with `Driver/library version mismatch`. Disabling
`unattended-upgrades.service` had not stopped it -- `apt-daily-upgrade.timer`
starts it. Fixed in our VM setup steps
(`testing/client-cluster-verification-test/README.md` section 1): disable
the apt-daily timers first, stop a running upgrade with SIGTERM, check
`dkms status`, then reboot. A pilot cluster could hit the same thing; the
fix is the node's, not ours.

### Cosmetic issue for later

The idle GPU also appeared under **Over-Provisioned** with Rs0/mo and
"none -- no smaller known SKU meets the SLA ceiling / no observed peak load
to size against". Peak 0% passes the over-provisioned test, but the only
useful finding for a 0%-busy GPU is idle. Proposed: don't report
over-provisioned for a workload whose observed peak is 0 (it is already
an idle finding).

Cost: ~3 h of VM at $0.226/hr, about $0.70.

### Re-running

Use the same steps; set the five image tags in `values-rehearsal.yaml` to
the commit you want to test. Do the apt-timer step before anything else.
