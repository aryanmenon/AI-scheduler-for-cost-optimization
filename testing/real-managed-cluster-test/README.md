# Real managed-Kubernetes-cluster test (GKE)

Item 3 of the 3-item pre-pilot list -- see `PROGRESS.md` sections 1 and 4.
This test targets a different thing than the other two:

- The fragmentation test proved detection logic fires correctly under
  real load and real thresholds.
- The heterogeneous-SKU test proved capability/pricing correctness across
  two different real GPU models.
- **This test proves the product survives contact with a real managed
  Kubernetes cluster**: real StorageClass-backed PVC persistence (both
  prior tests ran with `persistence.enabled: false` since bare vast.ai
  rentals have no default StorageClass -- this is the first time
  `persistence.enabled: true` gets exercised at all), real cloud-provider
  RBAC/Pod Security enforcement, and a real managed GPU device-plugin
  setup instead of a hand-rolled containerd config.

Because of that, this test does **not** need to re-prove real-time
thresholds (already proven) or cross-SKU pricing (already proven) -- one
GPU, one workload, the smoke-test thresholds, and a short run are enough.
The only quota this needs (`GPUS_ALL_REGIONS` + a per-model regional GPU
quota) is already approved -- see `PROGRESS.md` section 2 for exactly how,
if this needs redoing on a different GCP project later.

## 0. Prerequisites

- A GCP project with billing enabled (a free-trial-only account cannot
  provision GPUs regardless of quota -- upgrade first if this is a new
  project).
- GPU quota approved: `GPUS_ALL_REGIONS` >= 1 (global) and a per-model
  regional quota (e.g. `NVIDIA_T4_GPUS` in `us-central1`) >= 1. Check via:
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

## 1. Create the GKE cluster

A single zonal cluster with the GPU attached directly to its one node --
no separate node pool needed for a single-GPU test:

```bash
gcloud container clusters create gpu-optimizer-test \
  --zone=us-central1-a \
  --num-nodes=1 \
  --machine-type=n1-standard-4 \
  --accelerator=type=nvidia-tesla-t4,count=1,gpu-driver-version=default
```

`n1-standard-4` (not e2/n2) because T4 GPU attachment requires the N1
machine family. `gpu-driver-version=default` has GKE install the NVIDIA
driver automatically -- unlike the vast.ai/k3s tests, there's no manual
NVIDIA Container Toolkit / containerd runtime-config step here at all;
this is the actual point of testing a *managed* cluster.

This takes several minutes. Once done:

```bash
gcloud container clusters get-credentials gpu-optimizer-test --zone=us-central1-a
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
this one test-only image):

```bash
gcloud artifacts repositories create test-images \
  --repository-format=docker --location=us-central1

gcloud auth configure-docker us-central1-docker.pkg.dev

cd testing/fragmentation-and-load-test   # reusing that test's Dockerfile/server.py as-is
docker build -t us-central1-docker.pkg.dev/$(gcloud config get-value project)/test-images/tiny-model-server:test .
docker push us-central1-docker.pkg.dev/$(gcloud config get-value project)/test-images/tiny-model-server:test
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

GKE ships a default StorageClass out of the box (unlike the bare vast.ai
rentals in the other two tests) -- this is exactly what lets
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

Watch for a **Pod Security Admission** rejection specifically --
dcgm-exporter's `capabilities: add: ["SYS_ADMIN"]` requirement (needed to
talk to the NVIDIA driver) can be blocked by GKE's default Pod Security
Standards enforcement on newer cluster versions. If the dcgm-exporter pod
sits in `Pending`/`CreateContainerConfigError` with a Pod Security
Admission message in `kubectl describe pod`, label the `gpu-optimizer`
namespace to opt out of the restricted tier:
```bash
kubectl label namespace gpu-optimizer pod-security.kubernetes.io/enforce=privileged
```
This is itself a real, worth-recording finding if it happens -- a real
pilot customer's own namespace policies could hit the exact same wall,
and the chart/README should document the fix rather than assume it away.

## 7. Start load

```bash
kubectl -n inference port-forward svc/tiny-model 8001:8000 &

cd testing/fragmentation-and-load-test
pip install requests
python load_generator.py --target a=http://localhost:8001/generate --duration-hours 2
```
2 hours is enough -- smoke-test thresholds need ~1h streaks (see
`values-smoke-test.yaml`'s own comments), and this test's actual point is
infra survival, not re-proving thresholds.

## 8. What to check

Standard finding check (same query pattern as the other two tests, see
their READMEs) -- confirm at least an idle or over-provisioned finding
fires. Then the two things unique to this test:

**PVC persistence** (the real new thing here): note current row counts,
then force exactly the recreation scenario that destroyed data under
`emptyDir` in the other two tests:
```bash
kubectl -n gpu-optimizer get pvc   # confirm a real PVC is Bound, not Pending
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c ingestion-normalization -- \
  python3 -c "import sqlite3; print(sqlite3.connect('/data/normalized/normalized.db').execute('SELECT COUNT(*) FROM rollups').fetchone())"

kubectl -n gpu-optimizer delete pod -l app.kubernetes.io/name=gpu-telemetry-collector
kubectl -n gpu-optimizer wait --for=condition=ready pod -l app.kubernetes.io/name=gpu-telemetry-collector --timeout=120s

# same query again -- row count should be >= what it was before, not reset to 0
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c ingestion-normalization -- \
  python3 -c "import sqlite3; print(sqlite3.connect('/data/normalized/normalized.db').execute('SELECT COUNT(*) FROM rollups').fetchone())"
```

**Real RBAC**: confirm kube-state-metrics' ClusterRole actually works
under GKE's own RBAC enforcement (should be identical standard-Kubernetes
behavior, but this is the first real check off a bare/self-managed
cluster):
```bash
kubectl -n gpu-optimizer logs deploy/gpu-telemetry-collector -c kube-state-metrics --tail=20
# look for real pod/node data, not permission-denied errors
```

## 9. Teardown

```bash
kubectl delete -f k8s/workload.yaml -f k8s/namespace.yaml
helm uninstall gpu-telemetry -n gpu-optimizer
gcloud container clusters delete gpu-optimizer-test --zone=us-central1-a
gcloud artifacts repositories delete test-images --location=us-central1
```
Deleting the cluster stops all node/GPU billing immediately (GKE Standard
mode has no separate cluster-management fee for a single zonal cluster --
only the node's cost applies while it exists).
