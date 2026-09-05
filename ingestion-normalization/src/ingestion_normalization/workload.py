"""Derive a stable workload identity from a Kubernetes pod name.

A pod is a disposable replica; a "workload" (the Deployment, StatefulSet,
or Job that owns it) is what a customer actually thinks of as "the thing
running on this GPU." Tracking waste per-pod would reset every time a pod
is rescheduled -- tracking per-workload is what lets the savings estimator
say "this service has been idle 40% of the time for two weeks."

Kubernetes pod names follow a few well-known shapes:
  - Deployment:  <name>-<replicaset-hash>-<pod-suffix>   e.g. bert-large-7d4f469bfb-xk2p9
  - StatefulSet: <name>-<ordinal>                         e.g. finetune-job-4
  - Job:         <name>-<pod-suffix>                      e.g. data-loader-x7z2p
  - Bare pod:    <name>                                   e.g. redis

These are ambiguous in general (a StatefulSet ordinal and a bare name that
happens to end in a digit look identical), so patterns are tried from most
to least specific. When nothing matches confidently, the pod name is
returned unchanged rather than guessing wrong -- an unstripped suffix
costs a little grouping quality; a wrongly-stripped meaningful name
corrupts it.

Kubernetes generates random suffixes from an alphabet that deliberately
excludes vowels (to avoid accidentally spelling words) -- so matching
random-suffix tokens against a vowel-free character class, instead of
plain [a-z0-9], is what keeps a workload name like "data-loader" (a real
English word) from being misread as "data" + a fake "loader" hash.
"""
from __future__ import annotations

import re

# Vowel-free lowercase-alnum: the character class k8s's own random-suffix
# generator draws from. Excluding vowels is what disambiguates a genuine
# generated suffix from an ordinary word segment in the workload's name.
_SUFFIX_CHARS = "bcdfghjklmnpqrstvwxyz0-9"

# Deployment: k8s replicaset hash, followed by the pod's own suffix.
_DEPLOYMENT_RE = re.compile(rf"^(?P<base>.+)-[{_SUFFIX_CHARS}]{{4,10}}-[{_SUFFIX_CHARS}]{{5}}$")
# StatefulSet: purely numeric ordinal suffix.
_STATEFULSET_RE = re.compile(r"^(?P<base>.+)-\d+$")
# Job (or any single-suffix controller): one 5-char random-suffix token.
_JOB_RE = re.compile(rf"^(?P<base>.+)-[{_SUFFIX_CHARS}]{{5}}$")

_PATTERNS = (_DEPLOYMENT_RE, _STATEFULSET_RE, _JOB_RE)


def derive_workload_name(pod: str | None) -> str | None:
    if pod is None:
        return None

    for pattern in _PATTERNS:
        match = pattern.match(pod)
        if match:
            return match.group("base")

    return pod
