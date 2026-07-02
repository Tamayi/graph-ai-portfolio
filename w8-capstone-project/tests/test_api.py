"""Backend endpoint tests (FastAPI TestClient), fully mocked, no keys/network."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
from app.api import app
from src import structured
from tests.fakes import fake_report

client = TestClient(app)


@pytest.fixture
def no_datasets(tmp_path, monkeypatch):
    """An empty datasets dir - nothing built yet."""
    monkeypatch.setattr(config, "DATASETS_DIR", tmp_path)
    return tmp_path


def test_health_shape():
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert set(d["keys"]) == {"anthropic", "voyage"}
    assert "index_built" in d and "datasets_built" in d


def test_overview_no_datasets_returns_503(no_datasets):
    """Without built datasets the endpoint returns an explicit no-data state,
    never stand-in sample numbers."""
    r = client.get("/api/overview")
    assert r.status_code == 503


@pytest.fixture
def built_datasets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATASETS_DIR", tmp_path)
    monkeypatch.setattr(structured, "extract_report", fake_report)
    structured.build_datasets()
    return tmp_path


def test_overview_with_datasets(built_datasets):
    latest = max(structured.split_reports()[0])
    r = client.get("/api/overview")
    assert r.status_code == 200
    d = r.json()
    assert d["kpiNums"] and d["series"]
    assert d["provinces"] and d["zones"]
    assert d["sitrep_number"] == latest
    assert d["provinces"][0]["name"] == "Ituri"
    # sub-lines and secondary stats are populated from the report fields
    assert d["subs"]["new_conf_24h"] == 5      # fake report's new_confirmed_24h
    assert d["subs"]["hcw_cfr"] == 33.3        # 1 / 3 * 100
    assert d["secNums"]["suspects"] == 2
    assert d["secNums"]["recovered"] == latest  # fake sets recovered = num


def test_sitreps_all_indexed():
    """Holdout is disabled by default: every manifest report is indexed."""
    r = client.get("/api/sitreps")
    assert r.status_code == 200
    d = r.json()
    nums = sorted(int(x["sitrep_number"]) for x in d["reports"])
    assert d["holdout"] == []
    assert sorted(d["indexed"]) == nums and nums


def test_chat_maps_shape(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(config, "VOYAGE_API_KEY", "x")
    import src.chat as chatmod

    class FakeBot:
        def __init__(self, language="fr"):
            self.history = []

        def ask(self, message):
            return {"text": "Reponse", "charts": [{"title": "Letalite", "y_label": "%"}],
                    "sources": [{"sitrep_number": 42, "page": 2}]}

    monkeypatch.setattr(chatmod, "SitrepChat", FakeBot)
    r = client.post("/api/chat", json={"message": "letalite?", "lang": "fr"})
    assert r.status_code == 200
    d = r.json()
    assert d["text"] == "Reponse"
    assert d["chart"] == "cfr"
    assert d["cites"] == [{"src": "SitRep N 42", "loc": "p.2"}]


def test_chat_503_without_keys(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "VOYAGE_API_KEY", "")
    r = client.post("/api/chat", json={"message": "hi", "lang": "fr"})
    assert r.status_code == 503


def test_dq_assess_shape(monkeypatch):
    from src import data_quality
    monkeypatch.setattr(
        data_quality, "assess_single_structured",
        lambda n, lang: {"score": 80,
                         "dimensions": [{"key": "dim_completeness", "v": 70}],
                         "issues": [{"sev": "High", "cat": "cat_coverage",
                                     "loc": "p.4", "text": "x"}],
                         "narrative": "ok"})
    r = client.post("/api/data-quality/assess", json={"n": 39, "lang": "fr"})
    assert r.status_code == 200
    d = r.json()
    assert d["score"] == 80
    assert d["dimensions"][0]["key"] == "dim_completeness"
    assert d["issues"][0]["sev"] == "High"
    assert d["narrative"] == "ok"


def test_dq_compare_shape(monkeypatch):
    from src import data_quality
    monkeypatch.setattr(
        data_quality, "compare_structured",
        lambda a, b, lang: {"metrics": [{"m": "Cas", "a": "1", "b": "2",
                                         "d": "+1", "flag": "alert"}],
                            "issues": [{"sev": "High", "cat": "cat_consistency",
                                        "loc": "Tableau 1", "text": "deaths do not reconcile"}],
                            "sections": [{"type": "type_added", "text": "x"}],
                            "banner": "headline"})
    r = client.post("/api/data-quality/compare", json={"a": 38, "b": 39, "lang": "fr"})
    assert r.status_code == 200
    d = r.json()
    assert d["metrics"][0]["flag"] == "alert"
    assert d["issues"][0]["sev"] == "High"
    assert d["sections"][0]["type"] == "type_added"
    assert d["banner"] == "headline"


def test_dq_assess_503_without_keys(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "VOYAGE_API_KEY", "")
    r = client.post("/api/data-quality/assess", json={"n": 39, "lang": "fr"})
    assert r.status_code == 503


def test_topics_run_shape(monkeypatch):
    from src import topics
    monkeypatch.setattr(topics, "run_and_cache",
                        lambda lang="fr": [{"sitrep_number": 39, "date": "2026-06-23",
                                            "theme": "Financement", "detail": "x"}])
    monkeypatch.setattr(topics, "synthesise", lambda rows, lang="fr": "synth")
    r = client.post("/api/topics/run?lang=fr")
    assert r.status_code == 200
    d = r.json()
    assert d["rows"][0]["theme"] == "Financement"
    assert d["synthesis"] == "synth"


def test_topics_run_503_without_keys(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "VOYAGE_API_KEY", "")
    r = client.post("/api/topics/run?lang=fr")
    assert r.status_code == 503


def test_sitreps_resolve(monkeypatch):
    from src import uploader
    monkeypatch.setattr(uploader, "find_pdf_url",
                        lambda url: "https://insp.cd/wp-content/uploads/2026/06/sitrep-040.pdf")
    r = client.post("/api/sitreps/resolve",
                    json={"url": "https://insp.cd/sitrep-n040-mvb_23-06-2026/"})
    assert r.status_code == 200
    d = r.json()
    assert d["pdf_url"].endswith("sitrep-040.pdf")
    assert d["number"] == 40
    assert d["report_date"] == "2026-06-23"


def test_sitreps_ingest_url(monkeypatch):
    from src import uploader
    monkeypatch.setattr(uploader, "pdf_from_url", lambda url: (b"%PDF", "http://x/y.pdf"))
    monkeypatch.setattr(uploader, "add_sitrep",
                        lambda **kw: {"sitrep_number": 40, "report_date": "2026-06-23",
                                      "pages": 16, "reextracted": True, "reindexed": False})
    r = client.post("/api/sitreps/ingest-url",
                    json={"url": "https://insp.cd/sitrep-n040-mvb_23-06-2026/"})
    assert r.status_code == 200
    assert r.json()["sitrep_number"] == 40


def test_sitreps_ingest_file(monkeypatch):
    from src import uploader
    captured = {}

    def fake_add(**kw):
        captured.update(kw)
        return {"sitrep_number": 42, "report_date": "2026-06-25", "pages": 16,
                "reextracted": False, "reindexed": False}

    monkeypatch.setattr(uploader, "add_sitrep", fake_add)
    r = client.post("/api/sitreps/ingest-file",
                    files={"file": ("sitrep_042.pdf", b"%PDF-1.4 data", "application/pdf")},
                    data={"number": "42"})
    assert r.status_code == 200
    assert r.json()["sitrep_number"] == 42
    assert captured["number"] == 42
    assert captured["pdf_bytes"].startswith(b"%PDF")


def test_sitreps_ingest_file_rejects_non_pdf():
    r = client.post("/api/sitreps/ingest-file",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
