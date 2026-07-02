"""Data-layer tests: holdout split, dataset aggregation, chunking, validation."""
from __future__ import annotations

import json

import config
from src import structured
from src.ingest import chunk_markdown
from tests.fakes import fake_report


def test_split_reports_no_holdout_by_default():
    indexed, holdout = structured.split_reports()
    assert holdout == []
    assert indexed == sorted(indexed) and indexed


def test_split_reports_holdout(monkeypatch):
    monkeypatch.setattr(config, "HOLDOUT_RECENT_N", 3)
    indexed, holdout = structured.split_reports()
    assert holdout == sorted(indexed + holdout)[-3:]
    assert set(holdout).isdisjoint(indexed)


def _build(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATASETS_DIR", tmp_path)
    monkeypatch.setattr(structured, "extract_report", fake_report)
    structured.build_datasets()


def _load(tmp_path, name):
    return json.loads((tmp_path / name).read_text(encoding="utf-8"))


def test_build_datasets_shapes(tmp_path, monkeypatch):
    _build(tmp_path, monkeypatch)

    kpi = _load(tmp_path, "kpi_timeseries.json")
    assert kpi and "cumulative_confirmed" in kpi[0]

    prov = _load(tmp_path, "province_timeseries.json")
    assert prov and prov[0]["name"] == "Ituri"
    assert "sitrep_number" in prov[0]

    zone = _load(tmp_path, "zone_timeseries.json")
    assert zone and "confirmed" in zone[0]

    for pillar in ("laboratory", "contacts", "ipc"):
        rows = _load(tmp_path, f"{pillar}_timeseries.json")
        assert rows, f"{pillar} should have rows"

    # No vaccination campaign is reported in this outbreak.
    assert _load(tmp_path, "vaccination_timeseries.json") == []


def test_build_datasets_excludes_holdout(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOLDOUT_RECENT_N", 3)
    _build(tmp_path, monkeypatch)
    indexed, holdout = structured.split_reports()
    nums = {r["sitrep_number"] for r in _load(tmp_path, "kpi_timeseries.json")}
    assert holdout and nums.isdisjoint(holdout)
    assert max(nums) == max(indexed)


def test_dataset_validation(tmp_path, monkeypatch):
    _build(tmp_path, monkeypatch)
    kpi = sorted(_load(tmp_path, "kpi_timeseries.json"),
                 key=lambda r: r["sitrep_number"])

    confs = [r["cumulative_confirmed"] for r in kpi]
    assert confs == sorted(confs)  # cumulative confirmed is non-decreasing

    for r in kpi:
        assert 0 <= r["cfr_pct"] <= 100
        assert "sitrep_number" in r and "report_date" in r


def test_chunk_markdown_pages_and_size():
    text = "## Page 1\n" + "a" * 50 + "\n## Page 2\n" + "b" * 250
    chunks = list(chunk_markdown(text, size=100, overlap=20))

    assert {p for _, p in chunks} == {1, 2}

    p2 = [c for c, p in chunks if p == 2]
    assert all(len(c) <= 100 for c in p2)
    assert len(p2) >= 3
    # consecutive pieces overlap by `overlap` characters (step = size - overlap)
    assert p2[0][-20:] == p2[1][:20]
