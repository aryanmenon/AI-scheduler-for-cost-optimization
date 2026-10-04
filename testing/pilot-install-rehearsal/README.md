# Pilot install rehearsal

**Status: KIT READY, NOT RUN (2026-10-04).**

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

## Results

(to be filled in after the run)
