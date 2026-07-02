"""Tests for the SitRep uploader (no network, no keys, no real PDF parsing)."""
from __future__ import annotations

import csv

import pytest

import config
from src import uploader


def test_parse_number_variants():
    assert uploader.parse_number("sitrep-n040-mvb_23-06-2026") == 40
    assert uploader.parse_number("SitRep_MVE_RDC_N042_25_06_2026.pdf") == 42
    assert uploader.parse_number("N°007/2026") == 7
    assert uploader.parse_number("no number here") is None


def test_parse_date_variants():
    assert uploader.parse_date("sitrep-n040-mvb_23-06-2026") == "2026-06-23"
    assert uploader.parse_date("file_2026-06-25_final") == "2026-06-25"
    assert uploader.parse_date("nothing") is None


def test_looks_like_pdf_url():
    assert uploader.looks_like_pdf_url("https://x/y.pdf")
    assert uploader.looks_like_pdf_url("https://x/y.PDF?z=1")
    assert not uploader.looks_like_pdf_url("https://insp.cd/sitrep-n040/")


def test_find_pdf_url_prefers_uploads(monkeypatch):
    html = (b'<html><a href="/page">x</a>'
            b'<a href="https://insp.cd/other/doc.pdf">a</a>'
            b'<a href="/wp-content/uploads/2026/06/sitrep-040.pdf">b</a></html>')
    monkeypatch.setattr(uploader, "_http_get", lambda url, timeout=60: (html, "text/html"))
    out = uploader.find_pdf_url("https://insp.cd/sitrep-n040-mvb_23-06-2026/")
    assert out == "https://insp.cd/wp-content/uploads/2026/06/sitrep-040.pdf"


def test_find_pdf_url_none(monkeypatch):
    monkeypatch.setattr(uploader, "_http_get", lambda url, timeout=60: (b"<html>no pdf</html>", "text/html"))
    with pytest.raises(ValueError):
        uploader.find_pdf_url("https://insp.cd/x/")


def _setup_dirs(tmp_path, monkeypatch):
    md = tmp_path / "md"
    pdf = tmp_path / "pdf"
    md.mkdir()
    pdf.mkdir()
    monkeypatch.setattr(config, "SITREP_MD_DIR", md)
    monkeypatch.setattr(config, "SITREP_PDF_DIR", pdf)
    monkeypatch.setattr(uploader, "MANIFEST", tmp_path / "manifest.csv")
    # Avoid pypdf and any LLM/embedding work.
    monkeypatch.setattr(uploader, "pdf_to_markdown",
                        lambda b, title=None: "## Page 1\n\nhello\n\n## Page 2\n\nworld\n")
    return md, pdf


def test_add_sitrep_writes_md_manifest_pdf(tmp_path, monkeypatch):
    md, pdf = _setup_dirs(tmp_path, monkeypatch)
    result = uploader.add_sitrep(pdf_bytes=b"%PDF-1.4 fake", number=99,
                                 date="2026-07-01", pdf_url="http://x/y.pdf",
                                 reextract=False, reindex=False)

    assert result["sitrep_number"] == 99
    assert result["report_date"] == "2026-07-01"
    assert result["pages"] == 2
    assert (md / "sitrep_099_2026-07-01.md").exists()
    assert (pdf / "sitrep_099_2026-07-01.pdf").read_bytes() == b"%PDF-1.4 fake"

    with open(uploader.MANIFEST, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row = next(r for r in rows if r["sitrep_number"] == "99")
    assert row["md_filename"] == "sitrep_099_2026-07-01.md"
    assert row["pdf_url"] == "http://x/y.pdf"


def test_add_sitrep_overwrites_prior_date(tmp_path, monkeypatch):
    md, _ = _setup_dirs(tmp_path, monkeypatch)
    (md / "sitrep_040_2026-06-25.md").write_text("old", encoding="utf-8")

    uploader.add_sitrep(pdf_bytes=b"%PDF", number=40, date="2026-06-23",
                        reextract=False, reindex=False)

    assert not (md / "sitrep_040_2026-06-25.md").exists()  # stale removed
    assert (md / "sitrep_040_2026-06-23.md").exists()


def test_add_sitrep_detects_number_from_source(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    result = uploader.add_sitrep(pdf_bytes=b"%PDF", source="sitrep-n041-mvb_24-06-2026",
                                 reextract=False, reindex=False)
    assert result["sitrep_number"] == 41
    assert result["report_date"] == "2026-06-24"


def test_add_sitrep_runs_extract_and_index(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    from src import ingest, structured
    calls = {}
    monkeypatch.setattr(structured, "extract_report", lambda n, force=False: calls.setdefault("extract", n))
    monkeypatch.setattr(structured, "build_datasets", lambda **k: calls.setdefault("build", True))
    monkeypatch.setattr(ingest, "index_report", lambda n: 7)

    result = uploader.add_sitrep(pdf_bytes=b"%PDF", number=50, date="2026-07-02")
    assert result["reextracted"] is True
    assert result["reindexed"] is True
    assert result["chunks_indexed"] == 7
    assert calls["extract"] == 50
