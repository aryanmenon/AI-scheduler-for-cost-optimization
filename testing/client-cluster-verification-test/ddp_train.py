"""A deliberately data-loading-bound PyTorch DDP training job.

Stands in for a customer's multi-GPU training job in the client-cluster
verification test. Each sample takes --io-ms-per-sample of simulated I/O
(e.g. reading from slow remote storage) in the DataLoader workers, so the
GPUs spend much of their time waiting for data -- the low-utilization
multi-GPU pattern the product's "could use fewer GPUs" signal looks for.

Run with torchrun, one process per GPU:
  torchrun --nproc_per_node=2 ddp_train.py --train-hours 2 --hold-hours 1

Phases, each logged with a timestamp so the test can line up the
product's findings against what really happened:
  1. train for --train-hours (EPOCH_JSON per epoch on rank 0),
  2. hold for --hold-hours: processes stay alive with their CUDA context and
     memory but do no work -- an idle GPU still attached to the pod,
  3. exit. The pod completes and its GPUs are released (no pod attached).

Rerun the same command with fewer GPUs (and optionally more --num-workers)
to measure what "fewer GPUs" actually costs in throughput.

Output, one JSON object per line on rank 0's stdout:
  EPOCH_JSON {...}, PHASE_JSON {...}, TRAIN_SUMMARY_JSON {...}
"""
from __future__ import annotations

import argparse
import json
import os
import time

import torch
import torch.distributed as dist
import torch.nn as nn
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader, Dataset
from torch.utils.data.distributed import DistributedSampler


class SlowSyntheticImages(Dataset):
    def __init__(self, n: int, io_ms: float, image_size: int):
        self.n, self.io_s, self.size = n, io_ms / 1000.0, image_size

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, i: int):
        time.sleep(self.io_s)  # simulated slow storage read
        g = torch.Generator().manual_seed(i)
        return torch.randn(3, self.size, self.size, generator=g), i % 10


def make_model() -> nn.Module:
    def block(cin, cout):
        return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(), nn.MaxPool2d(2))
    return nn.Sequential(block(3, 64), block(64, 128), block(128, 256), block(256, 512),
                         nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(512, 10))


def emit(kind: str, payload: dict, rank: int) -> None:
    if rank == 0:
        print(f"{kind} " + json.dumps(payload), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="train")
    ap.add_argument("--train-hours", type=float, default=1.0)
    ap.add_argument("--max-epochs", type=int, default=None, help="stop after N epochs even if time remains")
    ap.add_argument("--hold-hours", type=float, default=0.0)
    ap.add_argument("--epoch-samples", type=int, default=20000, help="global samples per epoch")
    ap.add_argument("--batch-size", type=int, default=64, help="per-GPU batch size")
    ap.add_argument("--num-workers", type=int, default=2, help="DataLoader workers per GPU process")
    ap.add_argument("--io-ms-per-sample", type=float, default=8.0)
    ap.add_argument("--image-size", type=int, default=128)
    args = ap.parse_args()

    backend = "nccl" if torch.cuda.is_available() else "gloo"
    dist.init_process_group(backend)
    rank, world = dist.get_rank(), dist.get_world_size()
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    device = torch.device(f"cuda:{local_rank}" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.set_device(device)

    dataset = SlowSyntheticImages(args.epoch_samples, args.io_ms_per_sample, args.image_size)
    sampler = DistributedSampler(dataset, num_replicas=world, rank=rank, shuffle=True)
    loader = DataLoader(dataset, batch_size=args.batch_size, sampler=sampler,
                        num_workers=args.num_workers, pin_memory=device.type == "cuda",
                        persistent_workers=args.num_workers > 0)
    model = DDP(make_model().to(device), device_ids=[local_rank] if device.type == "cuda" else None)
    opt = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
    loss_fn = nn.CrossEntropyLoss()

    config = {k: v for k, v in vars(args).items()}
    config.update({"world_size": world, "device": device.type})
    emit("PHASE_JSON", {"phase": "train_start", "t": time.time(), "config": config}, rank)

    train_start = time.time()
    deadline = train_start + args.train_hours * 3600
    epochs, samples_done, epoch_times = 0, 0, []
    while time.time() < deadline and (args.max_epochs is None or epochs < args.max_epochs):
        sampler.set_epoch(epochs)
        t0 = time.time()
        n = 0
        for x, y in loader:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            loss_fn(model(x), y).backward()
            opt.step()
            n += x.size(0)
        if device.type == "cuda":
            torch.cuda.synchronize()
        dt = time.time() - t0
        global_samples = n * world
        epochs += 1
        samples_done += global_samples
        epoch_times.append(dt)
        emit("EPOCH_JSON", {"label": args.label, "epoch": epochs, "seconds": dt,
                            "samples_per_s": global_samples / dt, "t": time.time()}, rank)

    train_seconds = time.time() - train_start
    emit("PHASE_JSON", {"phase": "train_end", "t": time.time()}, rank)

    if args.hold_hours > 0:
        # Keep the CUDA context and a chunk of memory alive, doing no work:
        # an allocated-but-idle GPU, still attached to this pod.
        keep = torch.empty(256 * 1024 * 1024, dtype=torch.uint8, device=device) if device.type == "cuda" else None
        emit("PHASE_JSON", {"phase": "hold_start", "t": time.time()}, rank)
        time.sleep(args.hold_hours * 3600)
        del keep
        emit("PHASE_JSON", {"phase": "hold_end", "t": time.time()}, rank)

    emit("TRAIN_SUMMARY_JSON", {
        "label": args.label, "world_size": world, "num_workers_per_gpu": args.num_workers,
        "epochs": epochs, "train_seconds": train_seconds,
        "mean_epoch_seconds": sum(epoch_times) / len(epoch_times) if epoch_times else None,
        "samples_per_s": samples_done / train_seconds if train_seconds > 0 else None,
    }, rank)
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
