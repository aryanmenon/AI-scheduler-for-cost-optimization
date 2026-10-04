# Pilot outreach kit (internal — not for prospects)

## Who to approach first

Teams that run **their own GPUs on Kubernetes** and feel the bill:

- AI product companies serving models (LLMs, speech, vision, embeddings) on
  their own GPU nodes — Series A or later, a platform/infra team of 2+.
- Companies training or fine-tuning in-house on a shared GPU cluster.
- Enterprise ML platform teams running internal GPU clusters.

Not a fit yet: teams only using hosted APIs (no GPUs of their own), GPUs
outside Kubernetes, or fewer than ~4 GPUs (the waste won't justify a pilot).

Who to contact: Head of ML platform / MLOps, infra or platform engineering
lead, or the CTO at smaller companies. India first, but nothing in the
product is India-specific apart from ₹ pricing.

## What we can honestly claim (and the evidence)

| Claim | Evidence |
|---|---|
| Finds real waste in real production data | Microsoft's public Philly GPU-cluster trace (a 2017 deep-learning training cluster): 23% of GPU capacity sat below a 70% use target and was detected; 15.6% of GPU-hours carry a concrete recommendation (`testing/real-trace-replay/`) |
| Runs on real clusters, read-only | Installed and run on k3s (vast.ai) and Google GKE (L4 GPUs); RBAC is get/list/watch only |
| Right-sizing advice is tested on real GPUs | Found and fixed a flaw common to compute-only sizing (memory speed limits LLM serving); the fixed predictions held on a GPU they were not built from (`testing/rightsizing-mini-test/`) |
| Every recommendation states its cost | Expected per-request slowdown and memory-fit status on every downsize |

**Never claim**: customer results, "saves X%" for their cluster, customer
names, or that it's production-proven. We have no customers yet — the
pilot is how we get that evidence, and saying so is a strength with
engineers.

## First message (email)

> Subject: Finding wasted GPU spend in your Kubernetes cluster
>
> Hi {name},
>
> I'm building a tool that finds GPU waste in Kubernetes — idle GPUs, GPUs
> larger than their workload needs, quiet hours that could scale down —
> and prices it in rupees. It installs read-only in ~15 minutes, and no
> data leaves your cluster.
>
> On Microsoft's public production GPU trace it found waste with a concrete
> fix in about 1 in 6 GPU-hours. I'm looking for 3–5 teams to run a free 3–4 week
> pilot and tell me where it's wrong.
>
> Would a 20-minute call next week make sense? If GPU cost isn't a
> problem for you, a one-line "no" helps me too.
>
> {your name}

## LinkedIn connection note (300 characters)

> Hi {name} — I'm building a read-only tool that finds wasted GPU spend in
> Kubernetes clusters and prices it in ₹. Looking for a few teams running
> their own GPUs for a free pilot. Open to a quick chat?

## Discovery call questions

1. How many GPUs, which models, on which cloud or on-prem? Kubernetes?
2. Roughly what do GPUs cost you per month? Is anyone accountable for that number?
3. What do you serve or train on them? Interactive (latency matters) or batch?
4. Do you already know of idle or oversized GPUs? What stops you fixing them?
5. Do you use GPU sharing (MIG, time-slicing), autoscaling, or spot capacity?
6. What tooling do you use for cost today (Kubecost, cloud billing, spreadsheets)?
7. Who would install it, and what would your security team need to see?
8. What result in 4 weeks would make this worth paying for?

## Objections

- **"Security won't allow a third-party tool."** Read-only RBAC, no data
  leaves the cluster, and on GPU Operator clusters no privileged pod.
  Offer the Pilot Guide's security section and the chart to review first.
- **"We already use Kubecost / cloud cost tools."** Don't argue features
  you haven't verified. Ask: does it tell you *which GPU is too big for its
  load, what to move it to, and how much slower it will get* — and do you act
  on its reports today? If yes, they may not need us; if no, that's the gap.
- **"Our utilization metrics already look high."** GPU busy % reads high
  whenever any kernel runs — an LLM server at 20% real load can show 75%.
  That's exactly the waste the product separates out.
- **"We'd never downsize an interactive service."** Then don't: every
  recommendation states its slowdown. Idle GPUs and quiet hours cost
  nothing in latency.
