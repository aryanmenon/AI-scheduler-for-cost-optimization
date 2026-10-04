"""Turn real rental prices into the product's ₹/hour rate table.

Writes two files:
- rates-values.yaml: a Helm values overlay setting
  savingsEstimator.gpuHourlyRatesJson. Pass it with -f. (Don't use
  --set-string for JSON: Helm parses {...} as list syntax and silently
  mangles it.)
- rates.json: the same rates plus the raw inputs, for verify.py.

Use the per-GPU hourly price you actually pay for the phase-1 GPU, and the
current listed per-GPU price for every smaller GPU the product could
recommend (look them up on the rental site when you rent), so both the
product's estimates and the verification use real market rates.

Example:
  python3 rates.py --usd-inr 95.45 \\
    --rate "NVIDIA A100 80GB=1.10" --rate "NVIDIA L4=0.45" \\
    --rate "NVIDIA T4=0.20" --rate "NVIDIA A10=0.40" \\
    --phase1-gpu "NVIDIA A100 80GB"
"""
from __future__ import annotations

import argparse
import json


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usd-inr", type=float, required=True, help="exchange rate, ₹ per US$")
    ap.add_argument("--rate", action="append", required=True,
                    help='"<canonical GPU name>=<US$ per GPU-hour>", repeatable')
    ap.add_argument("--phase1-gpu", required=True, help="canonical name of the rented phase-1 GPU")
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args()

    usd = {}
    for item in args.rate:
        name, _, price = item.rpartition("=")
        usd[name.strip()] = float(price)
    if args.phase1_gpu not in usd:
        raise SystemExit(f"--phase1-gpu {args.phase1_gpu!r} has no --rate")
    inr = {name: round(price * args.usd_inr, 2) for name, price in usd.items()}

    rates_json = json.dumps(inr, sort_keys=True)
    with open(f"{args.out_dir}/rates-values.yaml", "w") as f:
        f.write("savingsEstimator:\n")
        f.write(f"  gpuHourlyRatesJson: {json.dumps(rates_json)}\n")
    with open(f"{args.out_dir}/rates.json", "w") as f:
        json.dump({"usd_inr": args.usd_inr, "phase1_gpu": args.phase1_gpu,
                   "usd_per_gpu_hour": usd, "inr_per_gpu_hour": inr}, f, indent=2, sort_keys=True)
    print("wrote rates-values.yaml and rates.json")
    print(json.dumps(inr, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
