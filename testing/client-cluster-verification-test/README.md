# Client-cluster verification test

**Status: KIT BUILT, NOT RUN YET.** Plan: Quick mode first, then Full mode.

Every earlier test checked whether the product *detects* waste. This one
checks whether its **₹ estimates and recommendations are right**, the way a
client would experience them: install the product on a GPU cluster running
realistic open-source workloads, let it recommend, **apply each
recommendation, re-run the identical load, and measure** what actually
happened to cost, latency and throughput.

## What gets verified

| Product claim | How it's checked | Pass if |
|---|---|---|
| Utilization it measures | Independent `nvidia-smi` log on the host | Hourly averages within a few points |
| Idle GPU (pod attached), ₹ wasted | Training job's own log of when it held its GPUs idle | Hours and ₹ match the real hold window at the real rental rate |
| GPU time with no pod | Job log: when the job exited and released its GPUs | Hours match |
| Each ₹ figure | Recomputed from its finding and the real rental rates | Matches |
| **Over-provisioned: "move vllm-main to <smaller GPU>"** | **Rent that GPU, replay the identical trace, compare** | p95 latency ≤ 1.5× before, errors ≤ 0.5%, keeps up with arrivals |
| Fragmentation: "these two can share a GPU" | Put both services on one GPU, replay both loads | Same criteria for both services |
| Multi-GPU: "this job could use fewer GPUs" | Re-run the job on 1 GPU (same and doubled data-loader workers) | 1 GPU keeps ≥ 90% of throughput |

Recurring-pattern findings need 7+ days of data and are out of scope.

## What runs on the "client cluster" (1 node, 4 GPUs)

| GPU | Workload (all public, open-source) | Should trigger |
|---|---|---|
| 0 | `vllm-main`: vLLM serving `Qwen/Qwen2.5-1.5B-Instruct`, driven by the real Azure LLM conversation trace (`load-main`) | over-provisioned → right-size; fragmentation |
| 1 | `vllm-side`: vLLM serving `Qwen/Qwen2.5-0.5B-Instruct`, 15% of the real Azure code trace (`load-side`) | over-provisioned; fragmentation (with GPU 0) |
| 2-3 | `train-2gpu`: PyTorch DDP job, deliberately data-loading-bound, then holds its GPUs idle, then exits | multi-GPU "fewer GPUs"; idle; then no-pod time |

Pinned versions, identical in every phase: `vllm/vllm-openai:v0.8.5.post1`,
`pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime`, `python:3.11-slim` (load
jobs). `--dtype half` and `VLLM_USE_V1=0` keep the same vLLM stack runnable
on every GPU the product might recommend, T4 included.

## Modes, time and GPUs

| | Quick (smoke-test thresholds, 1h) | Full (real thresholds, what a client runs) |
|---|---|---|
| Phase 1: 4× A100 VM | ~6 h: ~1 h setup, 4 h observe, ~1 h experiments | ~29 h: ~1 h setup, 26 h observe, ~2 h experiments |
| Phase 2: 1× recommended GPU | ~1.5 h | ~1.5 h |
| Rough cost | ~$25-50 | ~$90-180 |

Costs assume ~$0.7-1.5 per A100-hour; check live prices when renting.

Timeline parameters (used with `sed` below):

| | `HOURS` (loads) | `TRAIN` | `HOLD` | Training job exits at | Collect at |
|---|---|---|---|---|---|
| Quick | 4 | 1.5 | 1.5 | ~3.0 h | ≥ 4.25 h |
| Full | 26 | 18 | 5 | ~23 h | ≥ 26.25 h |

`HOLD` spans at least one full clock hour (Quick) / four (Full) so the idle
detector sees whole hourly buckets. The no-pod time after exit needs a full
clock hour too, which is why collection waits ~1.25 h after exit.

---

## 0. Before renting

1. Look up current per-GPU-hour prices on vast.ai for: the A100 you'll rent,
   and the smaller GPUs the product might recommend (L4, T4, A10, L40S).
2. Note today's ₹/$ rate.

## 1. Rent and prepare the phase-1 VM

Rent on vast.ai: **instance type "Linux Virtual Machine"** (not the default
container type -- Kubernetes can't run inside it), Ubuntu 22.04 VM template,
**4× A100** (40 or 80 GB, PCIe or SXM), ≥ 16 vCPU, ≥ 64 GB RAM, ≥ 200 GB
disk, NVIDIA driver **≥ 550** (the images are CUDA 12.4 builds). Write down
the real per-GPU-hour price.

SSH in, then:

```bash
# Stop background driver updates (they caused an NVML driver/library
# mismatch mid-test before). If nvidia-smi ever fails with that error: reboot.
sudo systemctl disable --now unattended-upgrades || true
nvidia-smi   # must list 4 A100s; note the driver version (>= 550)

# NVIDIA Container Toolkit (NVIDIA's documented apt install)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit tmux git python3-pip

# k3s
curl -sfL https://get.k3s.io | sh -
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config && sudo chown $USER ~/.kube/config

# Make nvidia the DEFAULT containerd runtime. Both blocks are required: a
# named nvidia runtime alone leaves pods (and the device plugin) on runc,
# failing with "Incompatible strategy detected auto" / NVML init errors.
sudo mkdir -p /var/lib/rancher/k3s/agent/etc/containerd
cat <<'EOF' | sudo tee /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
{{ template "base" . }}

[plugins.'io.containerd.cri.v1.runtime'.containerd]
  default_runtime_name = "nvidia"

[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.nvidia]
  runtime_type = "io.containerd.runc.v2"
  [plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.nvidia.options]
    BinaryName = "/usr/bin/nvidia-container-runtime"
EOF
sudo systemctl restart k3s

# NVIDIA device plugin: use the latest release tag from
# https://github.com/NVIDIA/k8s-device-plugin/releases
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/<release-tag>/deployments/static/nvidia-device-plugin.yml

# dcgm-exporter only schedules on nodes with this label
kubectl label node $(kubectl get nodes -o jsonpath='{.items[0].metadata.name}') nvidia.com/gpu.present=true

# Must print 4 before going further
kubectl get nodes -o jsonpath='{.items[0].status.capacity.nvidia\.com/gpu}'; echo

# Helm and Docker (Docker only to build the product images)
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
curl -fsSL https://get.docker.com | sudo sh
```

## 2. Get the code and build the product images

```bash
git clone -b claude/agent-skills-setup-fno99z https://github.com/aryanmenon/AI-scheduler-for-cost-optimization.git
cd AI-scheduler-for-cost-optimization
bash testing/client-cluster-verification-test/build_images.sh   # ~10 min
```

If the clone asks for credentials, type the token at the masked prompt --
never put it in the URL or paste it into chat.

The published GHCR images are private and built only from the default
branch, so they don't contain this branch's detectors; building here avoids
both problems.

## 3. Set the real prices, install the product

```bash
T=testing/client-cluster-verification-test
mkdir -p results/quick   # results/full for the Full run
python3 $T/rates.py --usd-inr <today's rate> --phase1-gpu "NVIDIA A100 80GB" \
  --rate "NVIDIA A100 80GB=<what you pay per GPU-hour>" \
  --rate "NVIDIA L4=<listed>" --rate "NVIDIA T4=<listed>" \
  --rate "NVIDIA A10=<listed>" --rate "NVIDIA L40S=<listed>" \
  --out-dir results/quick
```
Use `"NVIDIA A100 40GB"` for a 40 GB card. Every GPU the product could
recommend needs a rate, or that estimate falls back to an illustrative price.

```bash
helm install gpuopt deploy/helm/gpu-telemetry-collector -n gpu-optimizer --create-namespace \
  -f deploy/helm/gpu-telemetry-collector/values.yaml \
  -f $T/values-client-quick.yaml \
  -f $T/values-local-images.yaml \
  -f results/quick/rates-values.yaml
kubectl -n gpu-optimizer get pods -w   # wait until all are Running, then Ctrl+C
```
For Full mode use `values-client-full.yaml` and `results/full/`. Never pass
the rates JSON with `--set-string`: Helm reads `{...}` as list syntax and
silently mangles it -- that's why `rates.py` writes a values file.

## 4. Start the independent utilization log

```bash
tmux new -s smi
nvidia-smi --query-gpu=timestamp,index,name,utilization.gpu,memory.used --format=csv -l 60 > ~/nvsmi.csv
# Ctrl+B then D to detach
```
The host clock must be UTC (`date`); verify.py lines the two logs up by hour.

## 5. Deploy the client workloads

```bash
kubectl apply -f $T/k8s/namespace.yaml
kubectl -n client-sim create configmap client-sim-scripts \
  --from-file=$T/trace_load.py --from-file=$T/ddp_train.py
kubectl apply -f $T/k8s/vllm-main.yaml -f $T/k8s/vllm-side.yaml
kubectl -n client-sim get pods -w   # first start downloads images + models: 5-15 min
kubectl -n client-sim exec deploy/vllm-main -- nvidia-smi -L   # each should show a
kubectl -n client-sim exec deploy/vllm-side -- nvidia-smi -L   # different single GPU
```

## 6. Start the loads and the training job (this starts the clock)

Quick: `HOURS=4 TRAIN=1.5 HOLD=1.5`. Full: `HOURS=26 TRAIN=18 HOLD=5`.
```bash
HOURS=4; TRAIN=1.5; HOLD=1.5; IO_MS=8
sed "s/__HOURS__/$HOURS/" $T/k8s/load-main.yaml | kubectl apply -f -
sed "s/__HOURS__/$HOURS/" $T/k8s/load-side.yaml | kubectl apply -f -
sed -e "s/__TRAIN_HOURS__/$TRAIN/" -e "s/__HOLD_HOURS__/$HOLD/" -e "s/__IO_MS__/$IO_MS/" \
  $T/k8s/train-2gpu.yaml | kubectl apply -f -
date -u   # note the start time
```

After ~5 minutes, check the training GPUs with `nvidia-smi`. Aim for
roughly 15-35% utilization on each. If they're much lower or higher, change
`IO_MS` (lower = busier), then
`kubectl -n client-sim delete job train-2gpu` and re-apply. Do this before
the observation window matters, i.e. within the first ~15 minutes.

Progress checks at any time:
```bash
kubectl -n client-sim logs job/load-main --tail=3      # INTERVAL_JSON every 5 min
kubectl -n client-sim logs job/train-2gpu --tail=3     # EPOCH_JSON / PHASE_JSON
kubectl -n gpu-optimizer logs deploy/gpuopt-collector -c waste-detector --tail=5
```

## 7. Collect (as soon as the window ends, before anything restarts)

Export immediately. A restart or `helm upgrade` mid-test lost findings in
an earlier test.
```bash
R=results/quick
kubectl -n gpu-optimizer exec -i deploy/gpuopt-collector -c savings-estimator \
  -- python3 - < $T/dump_product_data.py > $R/product.json
for j in load-main load-side train-2gpu; do kubectl -n client-sim logs job/$j > $R/$j.log; done
cp ~/nvsmi.csv $R/nvsmi.csv
python3 -c "import json; d=json.load(open('$R/product.json')); print(len(d['findings']), 'findings,', len(d['estimates']), 'estimates')"
```
Note the recommendation for `vllm-main` (needed for phase 2):
```bash
python3 -c "
import json; d=json.load(open('$R/product.json'))
f={x['id']:x for x in d['findings']}
for e in d['estimates']:
    x=f.get(e['finding_id'],{})
    print(x.get('category'), x.get('workload'), e['basis'], round(e['amount_inr'] or 0), e['recommended_action'])"
```

## 8. Verification experiments on the same node

**8a. Fragmentation: both services on one GPU.** The training job has
exited, so all GPUs are free once the vLLM pods are gone.
```bash
kubectl -n client-sim delete deploy vllm-main vllm-side
sed "s/__GPU_INDEX__/0/" $T/k8s/colocate.yaml | kubectl apply -f -
kubectl -n client-sim get pods -w   # both coloc-* must reach Running/Ready
kubectl -n client-sim exec deploy/coloc-main -- nvidia-smi -L   # must show the
kubectl -n client-sim exec deploy/coloc-side -- nvidia-smi -L   # SAME GPU UUID
kubectl apply -f $T/k8s/load-coloc.yaml   # one trace pass, ~1 h
```
If a co-located server runs out of memory or crashes, that's a real result
(FAIL); record the pod logs rather than retrying with different settings.

**8b. Fewer GPUs (run while 8a's load is going; it uses other GPUs):**
```bash
for W in 2 4; do
  sed -e "s/__WORKERS__/$W/g" -e "s/__IO_MS__/$IO_MS/" $T/k8s/train-1gpu.yaml | kubectl apply -f -
  kubectl -n client-sim wait --for=condition=complete --timeout=3h job/train-1gpu-w$W
done
```

**8c. Collect, copy off the VM, destroy it:**
```bash
for j in load-coloc-main:coloc-main load-coloc-side:coloc-side train-1gpu-w2:train-1gpu-w2 train-1gpu-w4:train-1gpu-w4; do
  kubectl -n client-sim logs job/${j%%:*} > $R/${j##*:}.log
done
tar czf ~/results-quick.tgz $R
```
From your own machine: `scp -P <port> root@<vm-ip>:~/results-quick.tgz .`
Then **destroy** the instance in vast.ai (stopping still bills storage).

## 9. Phase 2: the recommended GPU

Rent **1× the GPU from step 7** (any vast.ai instance type is fine; the
product isn't needed here). Then:
```bash
pip install vllm==0.8.5.post1
VLLM_USE_V1=0 nohup python3 -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-1.5B-Instruct --served-model-name main --dtype half \
  --max-model-len 4096 --gpu-memory-utilization 0.90 --port 8000 > vllm.log 2>&1 &
curl -O https://raw.githubusercontent.com/aryanmenon/AI-scheduler-for-cost-optimization/claude/agent-skills-setup-fno99z/testing/client-cluster-verification-test/trace_load.py
tmux new -s p2
python3 trace_load.py --target http://localhost:8000 --model main --trace conv \
  --speed 1.0 --label phase2-main | tee phase2-main.log      # ~1 h
```
`--gpu-memory-utilization 0.90` here (vs 0.35 on the shared A100) is
deliberate: a client moving to a dedicated smaller GPU would give vLLM the
whole card. Copy `phase2-main.log` into `results/quick/`, note the real
price you paid, and destroy the instance.

## 10. Report

Re-run `rates.py` with the **real** phase-2 price into `results/quick/`
(same flags, corrected `--rate` for that GPU), then:
```bash
python3 testing/client-cluster-verification-test/verify.py results/quick > results/quick/REPORT.md
```
Paste REPORT.md back here. Then repeat everything with Full mode.

## Files

| File | Purpose |
|---|---|
| `trace_load.py` | Replays the real Azure LLM trace against vLLM's OpenAI API; records latency/errors/throughput |
| `ddp_train.py` | Data-loading-bound PyTorch DDP job: train, hold idle, exit; logs every phase |
| `k8s/*.yaml` | Namespace, the two vLLM services, load jobs, training jobs, co-location experiment |
| `values-client-quick.yaml`, `values-client-full.yaml` | Product thresholds per mode, persistence on |
| `values-local-images.yaml`, `build_images.sh` | Run this branch's code instead of the published images |
| `rates.py` | Real rental prices → the product's ₹ rate table (values file) + `rates.json` |
| `dump_product_data.py` | Exports findings, estimates and hourly rollups from the running product |
| `verify.py` | Predicted vs measured report |

## Known limits of this test

- **One client, one shape of workload.** It verifies the mechanics on
  realistic open-source workloads; it doesn't stand in for a real
  customer's traffic.
- **The co-location experiment bypasses the device plugin** (both pods set
  `NVIDIA_VISIBLE_DEVICES` to the same GPU instead of requesting one). It
  reproduces what time-slicing does -- one GPU, no memory isolation --
  while guaranteeing both land on the same GPU.
- **Phase 2 runs the load once (~1 h)**; phase 1's summary covers every
  loop. Same trace, same request sizes, so the distributions compare, but
  phase 1 has more samples.
- **The training job's data loading is simulated** (`time.sleep` per
  sample, like slow remote storage), so adding loader workers scales it
  cleanly. Real CPU-bound preprocessing may not scale as well.
