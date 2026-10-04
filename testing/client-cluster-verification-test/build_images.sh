#!/usr/bin/env bash
# Build the product's five images from THIS checkout and load them into
# k3s's containerd, so the test runs exactly the code on this branch.
#
# Why not the published GHCR images: they're private (pulling needs a
# token) and are only rebuilt from the default branch, so they would not
# contain this branch's detectors (multi-GPU signal, no-recommendation
# tier, fragmentation fixes). Build contexts mirror .github/workflows CI.
#
# Run from the repo root on the GPU VM:  bash testing/client-cluster-verification-test/build_images.sh
set -euo pipefail

build() {  # name context dockerfile
  echo "== building local/$1:test"
  sudo docker build -t "local/$1:test" -f "$3" "$2"
  sudo docker save "local/$1:test" | sudo k3s ctr images import -
}

build telemetry-collector     .                       telemetry-collector/Dockerfile
build ingestion-normalization .                       ingestion-normalization/Dockerfile
build waste-detector          .                       waste-detector/Dockerfile
build savings-estimator       .                       savings-estimator/Dockerfile
build dashboard               .                       dashboard/Dockerfile

echo "== images now in k3s:"
sudo k3s ctr images ls | grep 'local/' | awk '{print $1}'
