# GPU Cost Optimizer — Design-Partner Pilot

A free, 3–4 week pilot to find out how much of your GPU spend is waste, and
whether acting on our recommendations saves it without hurting your
services.

## What you get

- A ₹ breakdown of GPU waste in your cluster: idle GPUs, GPUs too large for
  their load, quiet hours that could scale down, and waste we can measure
  but not yet explain.
- Specific recommendations, each with its stated cost (expected slowdown,
  whether memory fit was checked) so you can judge it.
- A before/after measurement on one recommendation you choose to act on.
- Direct input into what we build next.

## What we ask

- ~1 hour of an engineer's time to install (see the Pilot Guide), plus a
  30-minute review call each in weeks 1 and 2.
- Your real ₹/hour per GPU model, so figures are yours, not list prices.
- Honest feedback, especially when a finding is wrong.
- If the pilot saves you money, permission to describe the result
  anonymously (no name without your written sign-off).

## Timeline

| When | What |
|---|---|
| Day 0 | Install (read-only, ~15 min), confirm GPUs are being scraped |
| Days 1–7 | Product collects data; nothing for you to do |
| Week 2 | Review call: walk through every finding, mark each useful / wrong / already known |
| Weeks 2–3 | You act on one recommendation of your choosing; product keeps measuring |
| Week 4 | Results call: measured saving vs predicted, and what was wrong |

## Success criteria (agreed up front)

1. At least one finding your team agrees is real waste they didn't already know about.
2. For the recommendation you act on: the measured saving is within the
   range we predicted, and your service's latency and error rates stay
   within the slowdown we stated.
3. Fewer than 1 in 5 findings marked "wrong" at the week 2 review.

If these aren't met, that's a result too — we'll tell you plainly.

## Data and confidentiality

All data stays in your cluster (see the Pilot Guide's security section).
We see only what you choose to show us on review calls. Uninstall takes two
commands and leaves nothing behind.

## After the pilot

No obligation. If it's useful, we'll propose pricing based on what it
saved you in the pilot.
