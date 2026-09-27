# Real managed-Kubernetes-cluster test (GKE)

Item 3 of the 3-item pre-pilot list -- see `PROGRESS.md` sections 1 and 4.
**Status: DONE, PASSED.** This test targets a different thing than the
other two:

- The fragmentation test proved detection logic fires correctly under
  real load and real thresholds.
- The heterogeneous-SKU test proved capability/pricing correctness across
  two different real GPU models.
- **This test proves the product survives contact with a real managed
  Kubernetes cluster**: real StorageClass-backed PVC persistence (both
  prior tests ran with `persistence.enabled: false` since bare vast.ai
  rentals have no default StorageClass -- this is the first time
  `persistence.enabled: true` gets exercised at all), real cloud-provider
  RBAC enforcement, and a real managed GPU device-plugin setup instead of
  a hand-rolled containerd config.

Because of that, this test does **not** need to re-prove real-time
thresholds (already proven) or cross-SKU pricing (already proven) -- one
GPU, one workload, the smoke-test thresholds, and a short run are enough.

**Result the one time this was actually run** (see `PROGRESS.md` section
2 for the full story): GKE cluster on an L4 GPU (`g2-standard-4`,
`asia-south1-b` -- T4 hit `GCE_STOCKOUT` in three different zones first).
A real `over_provisioned` finding fired (peak utilization 4.0%, real
smoke-test threshold, not lowered further); PVC persistence survived a
forced collector-pod deletion (23 rollup rows before and after); RBAC
came back clean under GKE's own enforcement. Three real product bugs
were found and fixed along the way -- **all three are already fixed in
this chart as of the commits below, so a re-run of this test should not
need to rediscover them**, but the fixes are worth understanding before
you start, since they explain several things below that would otherwise
look unnecessary:
1. dcgm-exporter requesting `nvidia.com/gpu` as a schedulable resource
   (an early, since-reverted approach) made it compete with real GPU
   workloads for the same finite per-node count and left it permanently
   `Pending` on a single-GPU node with an active workload. Fixed by
   giving it direct hostPath access to `/dev` and the driver directory
   instead, plus `privileged: true` (commits `5fc6ce5`, `09692a4`) --
   the same approach NVIDIA's own GPU-Operator dcgm-exporter deployments
   use.
2. Even with GPU access working, DCGM's Kubernetes pod-attribution never
   attached a `pod=`/`namespace=` label on GKE specifically: it assumes
   device IDs from the kubelet's pod-resources API are full GPU UUIDs by
   default, but GKE's device plugin reports device-name form (`nvidia0`)
   instead, and the ID match silently fails with no error logged
   anywhere. Fixed via `DCGM_EXPORTER_KUBERNETES_GPU_ID_TYPE=device-name`
   (commit `64a4033`).
3. With `persistence.enabled=true` against a *real* dynamically
   provisioned volume (GKE's PD CSI driver) for the first time, the
   collector pod's 5 containers -- each a distinct non-root UID sharing
   subPath-remapped views of one PVC -- all failed to open their SQLite
   file, because a real cloud volume mounts owned by root with
   restrictive permissions (unlike `emptyDir`, used in every prior test,
   which happens to come out writable regardless of UID). Fixed with a
   pod-level `securityContext.fsGroup` (commit `f80b910`).

## 0. Prerequisites

- A GCP project with billing enabled (a free-trial-only account cannot
  provision GPUs regardless of quota -- upgrade first if this is a new
  project).
- GPU quota approved: `GPUS_ALL_REGIONS` >= 1 (global) and a per-model
  regional quota (e.g. `NVIDIA_T4_GPUS` or `NVIDIA_L4_GPUS` in whichever
  region you target) >= 1. Check via:
  ```bash
  gcloud compute project-info describe --format="yaml(quotas)" | grep -B2 -A2 GPUS_ALL_REGIONS
  gcloud compute regions describe us-central1 --format="yaml(quotas)" | grep -B2 -A2 NVIDIA_T4_GPUS
  ```
  If either shows `limit: 0.0`, see `PROGRESS.md` section 2's exact
  `gcloud alpha quotas` command sequence before continuing -- the console
  UI cannot request an increase for a zero-usage quota, this isn't a
  navigation problem.
- A classic GitHub PAT with `read:packages` (for the GHCR pull secret in
  step 6 -- see the root README's prerequisites section for why it must be
  classic, not fine-grained).
- **Budget real time for `GCE_STOCKOUT`.** T4 (the cheapest/most common
  GPU to test with) is popular enough that real capacity exhaustion in a
  given zone is common, not an edge case -- the one real run of this test
  hit it in 3 different zones before switching to L4/`g2-standard-4`,
  which succeeded immediately. Don't sink more than ~15-20 minutes into
  any one zone; try another zone, or pivot to L4 outright, rather than
  waiting it out.

## 1. Create the GKE cluster

A single zonal cluster with the GPU attached directly to its one node --
no separate node pool needed for a single-GPU test. Check which zones
actually have the accelerator you want before picking one:

```bash
gcloud compute accelerator-types list --filter="name=nvidia-l4" --format="value(zone)"
```

```bash
gcloud container clusters create gpu-optimizer-test \
  --zone=asia-south1-b \
  --num-nodes=1 \
  --machine-type=g2-standard-4 \
  --accelerator=type=nvidia-l4,count=1,gpu-driver-version=default
```

`g2-standard-4` is the required machine family for L4 attachment (T4
instead needs `n1-standard-4` and `type=nvidia-tesla-t4` -- try that first
if you'd rather test against T4 and have quota, but expect to possibly
hit `GCE_STOCKOUT` and need to fall back to L4 or another zone).
`gpu-driver-version=default` has GKE install the NVIDIA driver
automatically -- unlike the vast.ai/k3s tests, there's no manual NVIDIA
Container Toolkit / containerd runtime-config step here at all; this is
the actual point of testing a *managed* cluster.

This takes several minutes. Once done:

```bash
gcloud container clusters get-credentials gpu-optimizer-test --zone=asia-south1-b
kubectl get nodes
kubectl describe nodes | grep -A5 "Allocatable:" | grep nvidia.com/gpu
```

The second command should show `nvidia.com/gpu: 1`. If it shows nothing,
the driver installation is likely still finishing -- wait a minute and
recheck (`kubectl get pods -n kube-system | grep nvidia` should show a
driver-installer DaemonSet pod completing).

## 2. Label the GPU node (check first, don't assume)

The chart's `dcgmExporter.nodeSelector` requires
`nvidia.com/gpu.present=true` (NVIDIA's own GPU Feature Discovery
convention). GKE may or may not set this automatically depending on
version/addon config -- check before assuming either way:

```bash
kubectl get nodes --show-labels | grep -o 'nvidia.com/gpu.present=[a-z]*'
```

If nothing prints, label it yourself:
```bash
kubectl label node $(kubectl get nodes -o jsonpath='{.items[0].metadata.name}') nvidia.com/gpu.present=true
```

## 3. Build and push the test workload image

Unlike the vast.ai tests (`k3s ctr images import` from a local build),
GKE nodes are Google-managed COS images with no local Docker access --
push to a real registry instead. Google Artifact Registry is the natural
choice here (same-project images pull with zero extra imagePullSecrets,
avoiding the whole GHCR fine-grained-vs-classic-PAT issue entirely for
this one test-only image). Use the same region as your cluster:

```bash
gcloud artifacts repositories create test-images \
  --repository-format=docker --location=asia-south1

gcloud auth configure-docker asia-south1-docker.pkg.dev

cd testing/fragmentation-and-load-test   # reusing that test's Dockerfile/server.py as-is
docker build -t asia-south1-docker.pkg.dev/$(gcloud config get-value project)/test-images/tiny-model-server:test .
docker push asia-south1-docker.pkg.dev/$(gcloud config get-value project)/test-images/tiny-model-server:test
```

**Real gotcha found live, not in the original plan**: the GKE node's
default Compute Engine service account does NOT automatically have pull
access to a same-project Artifact Registry repo -- image pulls fail with
`ErrImagePull` / 403. Grant it explicitly:

```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")
gcloud artifacts repositories add-iam-policy-binding test-images \
  --location=asia-south1 \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"
```

## 4. Deploy the workload

Edit `k8s/workload.yaml`, replacing `IMAGE_PLACEHOLDER` with the real
pushed image path from step 3. Then:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/workload.yaml
kubectl -n inference get pods -o wide   # confirm it lands on the GPU node and goes Ready
```

## 5. Verify a real default StorageClass exists

```bash
kubectl get storageclass
```

GKE ships a default StorageClass out of the box (`standard-rwo` at the
time of the one real run of this test) -- unlike the bare vast.ai
rentals in the other two tests, this is exactly what lets
`persistence.enabled: true` actually work here for the first time. No
`persistence.storageClassName` override needed; leaving it empty uses
whichever StorageClass is marked default.

## 6. Deploy the product

```bash
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io --docker-username=<your-github-username> \
  --docker-password=<classic-PAT-with-read:packages> \
  -n gpu-optimizer --dry-run=client -o yaml | kubectl apply -f -
# (create the namespace first if the secret command complains it's missing:
#  kubectl create namespace gpu-optimizer)

helm install gpu-telemetry deploy/helm/gpu-telemetry-collector \
  --namespace gpu-optimizer --create-namespace \
  -f deploy/helm/gpu-telemetry-collector/values.yaml \
  -f deploy/helm/gpu-telemetry-collector/values-smoke-test.yaml \
  --set persistence.enabled=true \
  --set global.imagePullSecrets[0].name=ghcr-secret
```

Note the override: `persistence.enabled=true` (the smoke-test values file
sets this `false` by default, matching the no-StorageClass vast.ai
rentals it was written for -- explicitly overriding it back on here is
the entire point of running this test on GKE instead).

The chart already ships fixes for the two real dcgm-exporter bugs found
during the one real run of this test (hostPath-based GPU access instead
of a competing resource request, plus the GKE-specific device-ID-type
fix for pod attribution -- see the top of this file), so dcgm-exporter
should reach `1/1 Running` directly without any manual intervention.
Confirm it did:

```bash
kubectl -n gpu-optimizer get pods
kubectl -n gpu-optimizer logs -l app.kubernetes.io/name=dcgm-exporter --tail=20
# look for "DCGM successfully initialized!" and "Kubernetes metrics collection enabled!"
```

If persistence is enabled, also confirm the collector pod reaches
`5/5 Running` (the fsGroup fix above) rather than sitting in
`CrashLoopBackOff` with `sqlite3.OperationalError: unable to open
database file`.

## 7. Start load

Run the load generator as a real in-cluster Kubernetes Job, not as a
local process from your own shell. **This matters**: during the one real
run of this test, the client shell (Google Cloud Shell) restarted twice
mid-run for reasons unrelated to the test itself, silently killing
whatever was running in that terminal (a `kubectl port-forward`, then
later the load generator process itself) and leaving gaps in rollup
`coverage_ratio` right when the detectors needed an unbroken streak. A
Job has no such dependency -- it keeps running as long as the cluster
does, and reaches the workload directly over in-cluster DNS with no
port-forward tunnel needed at all:

```bash
kubectl create configmap load-generator-script -n inference \
  --from-file=load_generator.py=testing/fragmentation-and-load-test/load_generator.py \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f testing/real-managed-cluster-test/k8s/load-generator-job.yaml

kubectl -n inference logs -f job/load-generator
```

2 hours (set inside `load-generator-job.yaml`) is enough -- smoke-test
thresholds need ~1h streaks (see `values-smoke-test.yaml`'s own
comments), and this test's actual point is infra survival, not
re-proving thresholds. Deleting the `inference` namespace at teardown
(step 9) cleans up the Job and its ConfigMap along with the workload.

## 8. What to check

Standard finding check (same query pattern as the other two tests, see
their READMEs) -- confirm at least an idle or over-provisioned finding
fires:
```bash
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c waste-detector -- python3 -c "
import sqlite3
conn = sqlite3.connect('/data/findings/findings.db')
cur = conn.cursor()
cur.execute('SELECT category, node, gpu_index, workload, metric_value FROM waste_findings ORDER BY id DESC')
for row in cur.fetchall(): print(row)
"
```
If nothing has fired yet, check the most recent hourly rollup's
`coverage_ratio` -- it needs to clear `min_coverage_ratio` (0.8 by
default) before the detector will trust it, which can take a little
past the first hour if there were any scrape gaps:
```bash
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c ingestion-normalization -- python3 -c "
import sqlite3
conn = sqlite3.connect('/data/normalized/normalized.db')
cur = conn.cursor()
cur.execute(\"SELECT granularity, workload, avg_utilization_pct, coverage_ratio, bucket_start FROM rollups ORDER BY id DESC LIMIT 15\")
for row in cur.fetchall(): print(row)
"
```

Then the two things unique to this test:

**PVC persistence** (the real new thing here): note current row counts,
then force exactly the recreation scenario that destroyed data under
`emptyDir` in the other two tests. Check the real label first --
the collector pod's label is `app.kubernetes.io/name=telemetry-collector`,
not `gpu-telemetry-collector` (a real gotcha: `kubectl get pods
--show-labels` if in doubt):
```bash
kubectl -n gpu-optimizer get pvc   # confirm a real PVC is Bound, not Pending
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c ingestion-normalization -- \
  python3 -c "import sqlite3; print(sqlite3.connect('/data/normalized/normalized.db').execute('SELECT COUNT(*) FROM rollups').fetchone())"

kubectl -n gpu-optimizer delete pod -l app.kubernetes.io/name=telemetry-collector
kubectl -n gpu-optimizer wait --for=condition=ready pod -l app.kubernetes.io/name=telemetry-collector --timeout=120s

# same query again -- row count should be >= what it was before, not reset to 0
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c ingestion-normalization -- \
  python3 -c "import sqlite3; print(sqlite3.connect('/data/normalized/normalized.db').execute('SELECT COUNT(*) FROM rollups').fetchone())"
```

**Real RBAC**: confirm kube-state-metrics' ClusterRole actually works
under GKE's own RBAC enforcement. It runs as its own separate Deployment,
not a sidecar container inside the collector pod:
```bash
kubectl -n gpu-optimizer logs deploy/gpu-telemetry-kube-state-metrics --tail=20
# look for "Communication with server successful" and no permission errors
```

## 9. Teardown

```bash
kubectl delete namespace inference   # cleans up the workload, load-generator Job, and its ConfigMap
helm uninstall gpu-telemetry -n gpu-optimizer
gcloud container clusters delete gpu-optimizer-test --zone=asia-south1-b --quiet
gcloud artifacts repositories delete test-images --location=asia-south1 --quiet
```
Deleting the cluster stops all node/GPU billing immediately (GKE Standard
mode has no separate cluster-management fee for a single zonal cluster --
only the node's cost applies while it exists).

**Real gotcha found live: always check for orphaned clusters
project-wide before declaring teardown done.** During the one real run
of this test, `gcloud container clusters list` at teardown time turned
up a *second*, forgotten cluster in a different zone/region -- a
leftover from an earlier `GCE_STOCKOUT`-interrupted `clusters create`
attempt that had silently failed to fully provision (`STATUS: ERROR`)
and was never cleaned up, sitting there consuming quota (and possibly
billing) the whole time unnoticed. Don't assume the only cluster left is
the one you think you created:
```bash
gcloud container clusters list
# delete anything unexpected the same way as above, then confirm:
gcloud container clusters list   # should be empty
gcloud compute instances list    # should also be empty
```
