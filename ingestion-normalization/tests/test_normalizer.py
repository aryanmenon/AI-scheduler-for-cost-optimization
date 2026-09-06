from ingestion_normalization.normalizer import UNATTRIBUTED, normalize_sample, normalize_samples
from ingestion_normalization.raw_reader import RawGPUSample


def _raw(**overrides) -> RawGPUSample:
    defaults = dict(
        id=1,
        scrape_run_id=1,
        scraped_at=1000.0,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        gpu_uuid="GPU-abc",
        gpu_model="NVIDIA A100-SXM4-80GB",
        namespace="inference",
        pod="bert-large-7d4f-xk2p9",
        container="model-server",
        utilization_pct=50.0,
        memory_used_mb=1000.0,
        memory_free_mb=2000.0,
        power_draw_w=200.0,
        sm_clock_mhz=1000.0,
    )
    defaults.update(overrides)
    return RawGPUSample(**defaults)


def test_normalize_derives_workload_from_pod():
    record = normalize_sample(_raw())
    assert record.workload == "bert-large"
    assert record.namespace == "inference"
    assert record.attributed is True


def test_normalize_computes_effective_tflops():
    record = normalize_sample(_raw(utilization_pct=50.0))
    # A100 80GB fp16_tflops = 312.0
    assert record.effective_tflops == 156.0
    assert record.capability_known is True


def test_normalize_unknown_gpu_model_leaves_effective_tflops_none():
    record = normalize_sample(_raw(gpu_model="Some Future GPU"))
    assert record.capability_known is False
    assert record.fp16_tflops is None
    assert record.effective_tflops is None


def test_mig_slice_effective_tflops_not_computed_from_full_gpu_capacity():
    # Regression: DCGM carries no MIG profile/fraction label, so a slice's
    # utilization_pct is relative to its own slice, not the full physical
    # GPU. Multiplying it by the physical GPU's fp16_tflops silently
    # overcounts capacity -- summed across enough slices it can exceed
    # what the physical card can actually do (an A100 80GB tops out at
    # 312 TFLOPS; 4 slices each reading ~90% "effective" of the whole GPU
    # would sum to ~1123 TFLOPS under the old, buggy math). Until MIG
    # profile data is available, these samples must report capacity as
    # unknown rather than a wrong, overcounted number.
    slices = [
        normalize_sample(_raw(gpu_instance_id=str(i), utilization_pct=90.0))
        for i in range(1, 5)
    ]

    assert all(r.effective_tflops is None for r in slices)
    assert all(r.capability_known is False for r in slices)

    physical_gpu_capacity = 312.0  # NVIDIA A100 80GB fp16 TFLOPS
    summed_effective_tflops = sum(r.effective_tflops or 0.0 for r in slices)
    assert summed_effective_tflops <= physical_gpu_capacity


def test_normalize_unattributed_sample_has_no_workload():
    record = normalize_sample(_raw(namespace=UNATTRIBUTED, pod=None, container=None))
    assert record.workload is None
    assert record.attributed is False


def test_normalize_none_utilization_leaves_effective_tflops_none():
    record = normalize_sample(_raw(utilization_pct=None))
    assert record.effective_tflops is None


def test_normalize_samples_preserves_order_and_count():
    raws = [_raw(id=i, scrape_run_id=i) for i in range(1, 4)]
    records = normalize_samples(raws)
    assert [r.scrape_run_id for r in records] == [1, 2, 3]
