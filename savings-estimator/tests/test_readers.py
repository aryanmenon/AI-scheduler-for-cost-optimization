import sqlite3

import pytest
from conftest import make_finding, make_rollup_record, write_findings, write_rollups

from savings_estimator.findings_reader import FindingsReader
from savings_estimator.rollup_reader import RollupReader


def test_findings_reader_reads_real_findings_db(tmp_path):
    path = str(tmp_path / "findings.db")
    write_findings(path, [make_finding("idle", confidence=0.9), make_finding("idle", gpu_index="1", confidence=0.3)])

    reader = FindingsReader(path)
    try:
        all_rows = reader.all_findings()
        assert len(all_rows) == 2
        high_confidence = reader.all_findings(min_confidence=0.5)
        assert len(high_confidence) == 1
        assert high_confidence[0].confidence == 0.9
    finally:
        reader.close()


def test_findings_reader_is_read_only(tmp_path):
    path = str(tmp_path / "findings.db")
    write_findings(path, [make_finding("idle")])
    reader = FindingsReader(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader._conn.execute("DELETE FROM waste_findings")
    finally:
        reader.close()


def test_rollup_reader_fetches_gpu_model_and_capability(tmp_path):
    path = str(tmp_path / "normalized.db")
    write_rollups(path, "hourly", [make_rollup_record(bucket_start=0.0)])

    reader = RollupReader(path)
    try:
        rows = reader.fetch_for_gpu("hourly", "gpu-node-1", "0", None, since=0.0, until=3600.0)
        assert len(rows) == 1
        assert rows[0].gpu_model == "NVIDIA A100-SXM4-80GB"
        assert rows[0].fp16_tflops == 312.0
    finally:
        reader.close()


def test_rollup_reader_filters_by_gpu_instance_id(tmp_path):
    path = str(tmp_path / "normalized.db")
    write_rollups(
        path,
        "hourly",
        [
            make_rollup_record(bucket_start=0.0, gpu_instance_id="1", workload="small-a"),
            make_rollup_record(bucket_start=0.0, gpu_instance_id="2", workload="small-b"),
        ],
    )

    reader = RollupReader(path)
    try:
        rows = reader.fetch_for_gpu("hourly", "gpu-node-1", "0", "1", since=0.0, until=3600.0)
        assert len(rows) == 1
        assert rows[0].workload == "small-a"
    finally:
        reader.close()


def test_rollup_reader_is_read_only(tmp_path):
    path = str(tmp_path / "normalized.db")
    write_rollups(path, "hourly", [make_rollup_record(bucket_start=0.0)])
    reader = RollupReader(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader._conn.execute("DELETE FROM rollups")
    finally:
        reader.close()
