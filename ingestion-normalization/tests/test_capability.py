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
