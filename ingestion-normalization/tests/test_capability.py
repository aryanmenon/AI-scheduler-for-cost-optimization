from ingestion_normalization.capability import lookup_capability


def test_a100_80gb_variants_resolve_to_same_family():
    for name in ["NVIDIA A100-SXM4-80GB", "NVIDIA A100 80GB PCIe", "A100"]:
        cap = lookup_capability(name)
        assert cap.known
        assert cap.mem_capacity_gb == 80.0
        assert cap.fp16_tflops == 312.0


def test_a100_40gb_distinguished_from_80gb():
    cap = lookup_capability("NVIDIA A100-SXM4-40GB")
    assert cap.mem_capacity_gb == 40.0


def test_h100_sxm_and_pcie_distinguished():
    sxm = lookup_capability("NVIDIA H100-SXM5-80GB")
    pcie = lookup_capability("NVIDIA H100 PCIe 80GB")
    assert sxm.fp16_tflops != pcie.fp16_tflops
    assert sxm.fp16_tflops == 989.0
    assert pcie.fp16_tflops == 756.0


def test_t4_resolves():
    cap = lookup_capability("Tesla T4")
    assert cap.known
    assert cap.fp16_tflops == 65.0


def test_a10_not_confused_with_a100():
    cap = lookup_capability("NVIDIA A10")
    assert cap.known
    assert cap.mem_capacity_gb == 24.0


def test_l4_not_confused_with_l40s():
    l4 = lookup_capability("NVIDIA L4")
    l40s = lookup_capability("NVIDIA L40S")
    assert l4.fp16_tflops != l40s.fp16_tflops
    assert l4.mem_capacity_gb == 24.0
    assert l40s.mem_capacity_gb == 48.0


def test_unknown_model_returns_explicit_unknown_rather_than_guess():
    cap = lookup_capability("Some Future GPU XYZ-9000")
    assert not cap.known
    assert cap.fp16_tflops is None
    assert cap.mem_bandwidth_gbps is None


def test_none_model_name_returns_unknown():
    cap = lookup_capability(None)
    assert not cap.known


def test_all_known_capabilities_returns_deduplicated_list():
    from ingestion_normalization.capability import all_known_capabilities

    caps = all_known_capabilities()
    names = [c.canonical_name for c in caps]
    assert len(names) == len(set(names))  # no duplicates
    assert "NVIDIA A100 80GB" in names
    assert "NVIDIA T4" in names
    assert all(c.known for c in caps)


def test_consumer_gpu_known_and_priceable_but_not_recommendable():
    # Consumer/gaming SKUs must be known (so their own telemetry can be
    # priced) but never recommendable (so ceiling.py's right-sizing search
    # never suggests one as a target for someone else's finding -- no
    # real cluster racks a GeForce card as a node pool option).
    for name in [
        "NVIDIA GeForce RTX 3060",
        "NVIDIA GeForce RTX 3090",
        "NVIDIA GeForce RTX 4060",
        "NVIDIA GeForce RTX 4060 Ti",
    ]:
        cap = lookup_capability(name)
        assert cap.known, f"{name} should be known/priceable"
        assert not cap.recommendable, f"{name} should not be recommendable"


def test_4060_ti_not_confused_with_plain_4060():
    # "4060 Ti"'s DCGM modelName also contains "4060" as a substring --
    # without the more specific pattern taking precedence, this would
    # silently resolve to the plain 4060's TFLOPS/price instead.
    ti = lookup_capability("NVIDIA GeForce RTX 4060 Ti")
    plain = lookup_capability("NVIDIA GeForce RTX 4060")
    assert ti.fp16_tflops != plain.fp16_tflops
    assert ti.fp16_tflops == 88.25
    assert plain.fp16_tflops == 60.5


def test_datacenter_gpus_remain_recommendable():
    for name in ["NVIDIA T4", "NVIDIA A10", "NVIDIA A100 80GB"]:
        cap = lookup_capability(name)
        assert cap.recommendable, f"{name} should still be recommendable"
