from ingestion_normalization.capability import lookup_capability

from savings_estimator.pricing import (
    CUSTOMER_PROVIDED_SOURCE,
    ILLUSTRATIVE_DEFAULT_SOURCE,
    lookup_price,
    parse_rate_overrides,
)


def test_known_gpu_gets_illustrative_default_rate():
    cap = lookup_capability("NVIDIA A100-SXM4-80GB")
    price = lookup_price(cap, rate_overrides={})
    assert price.known
    assert price.source == ILLUSTRATIVE_DEFAULT_SOURCE
    assert price.hourly_usd == 3.50


def test_customer_override_takes_precedence_over_default():
    cap = lookup_capability("NVIDIA A100-SXM4-80GB")
    price = lookup_price(cap, rate_overrides={"NVIDIA A100 80GB": 2.10})
    assert price.source == CUSTOMER_PROVIDED_SOURCE
    assert price.hourly_usd == 2.10


def test_unknown_gpu_model_is_unpriceable():
    cap = lookup_capability("Some Future GPU")
    price = lookup_price(cap, rate_overrides={})
    assert not price.known
    assert price.hourly_usd is None


def test_h100_sxm_and_pcie_have_different_rates():
    sxm_price = lookup_price(lookup_capability("NVIDIA H100-SXM5-80GB"), {})
    pcie_price = lookup_price(lookup_capability("NVIDIA H100 PCIe 80GB"), {})
    assert sxm_price.hourly_usd != pcie_price.hourly_usd


def test_parse_rate_overrides_valid_json():
    overrides = parse_rate_overrides('{"NVIDIA A100 80GB": 2.75, "NVIDIA T4": 0.35}')
    assert overrides == {"NVIDIA A100 80GB": 2.75, "NVIDIA T4": 0.35}


def test_parse_rate_overrides_none_returns_empty():
    assert parse_rate_overrides(None) == {}


def test_parse_rate_overrides_invalid_json_returns_empty():
    assert parse_rate_overrides("not json") == {}


def test_parse_rate_overrides_non_object_json_returns_empty():
    assert parse_rate_overrides("[1, 2, 3]") == {}
