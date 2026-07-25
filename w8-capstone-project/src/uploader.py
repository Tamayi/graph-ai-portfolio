"""Add or replace a single SitRep from a page URL, a PDF URL, or an upload.

Three entry points feed one pipeline:
  * a report page URL (e.g. https://insp.cd/sitrep-n040-mvb_23-06-2026/) - the
    page is fetched and the first PDF link on it is used;
  * a direct PDF URL;
  * raw PDF bytes (a file uploaded from the browser).

The PDF is archived, its text is extracted to markdown (one "## Page N" section
per page, matching the rest of the corpus), the markdown file and manifest row
are written - overwriting any existing report with the same number - and the
structured extraction and datasets are rebuilt. Re-embedding into the vector
index is best-effort and only runs when the keys are configured.

The SitRep number and date are detected from the URL slug, the PDF filename or
the document text, and can be overridden explicitly.
"""
from __future__ import annotations

import base64
import binascii
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

UA = "Mozilla/5.0 (sitrep-uploader)"
MANIFEST = config.DATA_DIR / "sitreps" / "manifest.csv"
_FIELDS = ["sitrep_number", "report_date", "title", "pdf_url", "md_filename", "chars"]


# --- HTTP ------------------------------------------------------------------

def _encode_url(url: str) -> str:
    """Percent-encode non-ASCII characters in the URL (degree signs, etc.)."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, quote(p.path, safe="/%"),
                       quote(p.query, safe="=&%"), p.fragment))


def _http_get(url: str, timeout: int = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(_encode_url(url), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read(), resp.headers.get("Content-Type", "")


# --- Resolve a PDF from a page or PDF URL ----------------------------------

_PDF_HREF_RE = re.compile(r'href=["\']([^"\']+?\.pdf)["\']', re.I)
# PDF Embedder plugin: the PDF URL is base64-encoded JSON in a "pdfemb-data" param.
_PDFEMB_RE = re.compile(r'pdfemb-data=([A-Za-z0-9_-]+)')


def _pdfemb_url(html: str) -> str | None:
    """Extract the PDF URL from a PDF Embedder ``pdfemb-data`` blob, if present."""
    for blob in _PDFEMB_RE.findall(html):
        padded = blob + "=" * (-len(blob) % 4)
        try:
            data = json.loads(base64.urlsafe_b64decode(padded))
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        url = data.get("url")
        if url:
            return url
    return None


def find_pdf_url(page_url: str) -> str:
    """Return the first PDF link on a report page, as an absolute URL."""
    html, _ = _http_get(page_url)
    text = html.decode("utf-8", "ignore")
    hrefs = _PDF_HREF_RE.findall(text)
    if hrefs:
        # Prefer the uploaded document when several links are present.
        hrefs.sort(key=lambda h: 0 if "wp-content/uploads" in h.lower() else 1)
        return urljoin(page_url, hrefs[0])
    # Fall back to the PDF Embedder plugin, which has no plain .pdf href.
    embedded = _pdfemb_url(text)
    if embedded:
        return urljoin(page_url, embedded)
    raise ValueError(f"No PDF link found on {page_url}")


def fetch_pdf(url: str) -> bytes:
    data, ctype = _http_get(url)
    if not (data.startswith(b"%PDF") or "pdf" in ctype.lower()):
        raise ValueError(f"URL did not return a PDF: {url}")
    return data


def looks_like_pdf_url(url: str) -> bool:
    return url.lower().split("?")[0].rstrip("/").endswith(".pdf")


def pdf_from_url(url: str) -> tuple[bytes, str]:
    """Resolve a page-or-PDF URL to (pdf_bytes, pdf_url)."""
    if looks_like_pdf_url(url):
        return fetch_pdf(url), url
    pdf_url = find_pdf_url(url)
    return fetch_pdf(pdf_url), pdf_url


# --- PDF -> markdown -------------------------------------------------------

def pdf_to_markdown(pdf_bytes: bytes, title: str | None = None) -> str:
    """Extract text page by page into the corpus's "## Page N" markdown shape.

    Uses PyMuPDF, which recovers the multi-column cover page and the dense
    tables in these SitReps far better than a naive stream reader (it keeps the
    cumulative-case figures and per-zone tables that a plain extractor drops or
    scrambles).
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        parts: list[str] = []
        if title:
            parts.append(f"# {title}")
        for i, page in enumerate(doc, 1):
            try:
                txt = page.get_text("text").strip()
            except Exception:  # noqa: BLE001 - a single bad page should not abort
                txt = ""
            parts.append(f"## Page {i}\n\n{txt}")
    finally:
        doc.close()
    return "\n\n\n".join(parts).strip() + "\n"


# --- Number / date detection ----------------------------------------------

_NUM_RE = re.compile(r"n[°o\s_-]*0*(\d{1,3})", re.I)
_DATE_DMY = re.compile(r"(\d{1,2})[-_/](\d{1,2})[-_/](\d{4})")
_DATE_YMD = re.compile(r"(\d{4})[-_/](\d{1,2})[-_/](\d{1,2})")


def parse_number(*sources: str) -> int | None:
    for s in sources:
        m = _NUM_RE.search(s or "")
        if m:
            return int(m.group(1))
    return None


def parse_date(*sources: str) -> str | None:
    for s in sources:
        if not s:
            continue
        m = _DATE_YMD.search(s)
        if m:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        m = _DATE_DMY.search(s)
        if m:
            d, mo, y = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    return None


# --- Manifest --------------------------------------------------------------

def _manifest_rows() -> list[dict]:
    if not MANIFEST.exists():
        return []
    with MANIFEST.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _existing_row(num: int) -> dict | None:
    for r in _manifest_rows():
        if int(r["sitrep_number"]) == num:
            return r
    return None


def _write_manifest(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: int(r["sitrep_number"]))
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _FIELDS})


# --- Add / replace a report ------------------------------------------------

def add_sitrep_events(*, pdf_bytes: bytes, source: str = "", number: int | None = None,
                      date: str | None = None, pdf_url: str = "", title: str = "",
                      reextract: bool = True, reindex: bool = True):
    """Write the PDF + markdown + manifest, yielding a progress event per step.

    Each yielded value is a ``{"step": <key>, ...}`` dict describing the step
    about to run; the final value is ``{"result": <summary>}``. The document is
    always written first; re-extraction (Anthropic) and re-indexing (Voyage) are
    best-effort so a missing key or dependency never loses the upload.
    """
    num = number or parse_number(source, title, pdf_url)
    if num is None:
        raise ValueError(
            "Could not determine the SitRep number; pass it explicitly.")

    existing = _existing_row(num) or {}
    rdate = (date or existing.get("report_date")
             or parse_date(source, pdf_url, title) or "unknown")

    config.SITREP_PDF_DIR.mkdir(parents=True, exist_ok=True)
    config.SITREP_MD_DIR.mkdir(parents=True, exist_ok=True)

    (config.SITREP_PDF_DIR / f"sitrep_{num:03d}_{rdate}.pdf").write_bytes(pdf_bytes)

    yield {"step": "read", "sitrep_number": num}
    # Remove any prior markdown for this number (its date may differ).
    for old in config.SITREP_MD_DIR.glob(f"sitrep_{num:03d}_*.md"):
        old.unlink()
    md_name = f"sitrep_{num:03d}_{rdate}.md"
    md = pdf_to_markdown(pdf_bytes, title or f"SitRep N°{num:03d}")
    (config.SITREP_MD_DIR / md_name).write_text(md, encoding="utf-8")

    rows = [r for r in _manifest_rows() if int(r["sitrep_number"]) != num]
    rows.append({"sitrep_number": str(num), "report_date": rdate,
                 "title": title or existing.get("title", ""),
                 "pdf_url": pdf_url or existing.get("pdf_url", ""),
                 "md_filename": md_name, "chars": str(len(md))})
    _write_manifest(rows)

    result = {"sitrep_number": num, "report_date": rdate, "md_filename": md_name,
              "pages": md.count("## Page "), "chars": len(md),
              "pdf_url": pdf_url or existing.get("pdf_url", ""),
              "reextracted": False, "reindexed": False}

    yield from reprocess_events(num, reextract=reextract, reindex=reindex,
                                result=result)


def reprocess_events(num: int, *, reextract: bool = True, reindex: bool = True,
                     result: dict | None = None):
    """Re-run extraction and indexing for one report, yielding step events.

    Used on its own to reprocess an already-archived report, and by
    :func:`add_sitrep_events` as the tail of a fresh ingest. Both steps are
    best-effort: a failure is recorded on the result rather than raised.
    """
    if result is None:
        result = {"sitrep_number": num, "reprocessed": True,
                  "reextracted": False, "reindexed": False}

    if reextract:
        yield {"step": "extract", "sitrep_number": num}
        try:
            from src import structured
            structured.extract_report(num, force=True)
            structured.build_datasets(force=False)
            result["reextracted"] = True
        except Exception as e:  # noqa: BLE001 - report, do not lose the upload
            result["reextract_error"] = str(e)

    if reindex:
        yield {"step": "index", "sitrep_number": num}
        try:
            from src import ingest
            result["chunks_indexed"] = ingest.index_report(num)
            result["reindexed"] = True
        except Exception as e:  # noqa: BLE001
            result["reindex_error"] = str(e)

    yield {"result": result}


def add_sitrep(*, pdf_bytes: bytes, source: str = "", number: int | None = None,
               date: str | None = None, pdf_url: str = "", title: str = "",
               reextract: bool = True, reindex: bool = True) -> dict:
    """Add/replace a report and return its summary (non-streaming wrapper).

    Drives :func:`add_sitrep_events` to completion; see it for behaviour.
    """
    result: dict = {}
    for ev in add_sitrep_events(
            pdf_bytes=pdf_bytes, source=source, number=number, date=date,
            pdf_url=pdf_url, title=title, reextract=reextract, reindex=reindex):
        if "result" in ev:
            result = ev["result"]
    return result
