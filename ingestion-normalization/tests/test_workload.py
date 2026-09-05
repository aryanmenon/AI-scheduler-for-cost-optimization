from ingestion_normalization.workload import derive_workload_name


def test_deployment_style_pod_strips_both_suffixes():
    assert derive_workload_name("bert-large-7d4f-xk2p9") == "bert-large"


def test_deployment_style_base_with_digits_preserved():
    assert derive_workload_name("llama-70b-6c9d-p2q7r") == "llama-70b"


def test_statefulset_style_pod_strips_ordinal():
    assert derive_workload_name("finetune-job-4") == "finetune-job"


def test_job_style_pod_strips_single_suffix():
    assert derive_workload_name("data-loader-x7z2p") == "data-loader"


def test_bare_pod_name_returned_unchanged():
    assert derive_workload_name("redis") == "redis"


def test_none_pod_returns_none():
    assert derive_workload_name(None) is None


def test_english_word_suffix_not_mistaken_for_hash():
    # "loader" is a real word (contains vowels) -- must not be misread as
    # a fake replicaset hash the way a plain [a-z0-9]{4,10} class would.
    assert derive_workload_name("data-loader-x7z2p") == "data-loader"


def test_mig_fixture_pod_names():
    assert derive_workload_name("small-model-a-7d4f-x1y2z") == "small-model-a"
    assert derive_workload_name("small-model-b-9c1d-p3q4r") == "small-model-b"
