import os

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return f.read()


@pytest.fixture
def dcgm_text() -> str:
    return _read_fixture("dcgm_sample.prom")


@pytest.fixture
def ksm_text() -> str:
    return _read_fixture("ksm_sample.prom")
