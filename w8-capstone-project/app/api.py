"""FastAPI backend for the BVD/MVE SitRep app.

Wraps the existing modules (chat, structured, data_quality, topics, retriever)
and serves the Claude Design frontend from ./frontend. The frontend renders the
approved screens and calls these endpoints; when a dataset has not been built
yet the relevant endpoint returns an explicit no-data state (no sample data).

Run:
    uvicorn app.api:app --reload --port 8007
then open http://localhost:8007

Heavy imports (anthropic, voyageai, chromadb) are done lazily inside endpoints
so the server starts even before keys or the index are in place; those endpoints
return a clear error until the environment is ready.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
import config  # noqa: E402

# Log to the uvicorn error stream so handler failures show a full traceback in
# the server console instead of a bare "503 Service Unavailable" access line.
logger = logging.getLogger("uvicorn.error").getChild("sitrep")

app = FastAPI(title="BVD/MVE SitRep API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

FRONTEND = ROOT / "frontend"


# --- Models ----------------------------------------------------------------
class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    lang: str = "fr"
    history: list[ChatTurn] = []


class CompareRequest(BaseModel):
    a: int
    b: int
    lang: str = "fr"


class AssessRequest(BaseModel):
    n: int
    lang: str = "fr"


class IngestUrlRequest(BaseModel):
    url: str
    number: int | None = None
    date: str | None = None
    reextract: bool = True
    reindex: bool = True


# --- Helpers ---------------------------------------------------------------
def _load_kpi() -> list[dict]:
    """KPI time series from the built dataset. Empty if it has not been built.

    There is deliberately no sample-data fallback: a missing dataset surfaces
    as an explicit no-data state (see overview()), never as stand-in numbers.
    """
    import json
    p = config.DATASETS_DIR / "kpi_timeseries.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


# --- Endpoints -------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    keys = {"anthropic": bool(config.ANTHROPIC_API_KEY),
            "voyage": bool(config.VOYAGE_API_KEY)}
    index = (config.CHROMA_DIR.exists())
    datasets = (config.DATASETS_DIR / "kpi_timeseries.json").exists()
    return {"ok": True, "keys": keys, "index_built": index,
            "datasets_built": datasets}


@app.get("/api/overview")
def overview() -> dict:
    """Dashboard data in the frontend's field shapes, from structured datasets.

    Uses the latest indexed (non-holdout) report. Returns 503 until the
    datasets are built - the dashboard shows a no-data state rather than
    stand-in sample numbers.
    """
    kpi = _load_kpi()
    indexed = [r for r in kpi if not r.get("is_holdout", False)] or kpi
    if not indexed:
        raise HTTPException(503, "No datasets yet. Run python -m src.structured.")
    latest = indexed[-1]

    series = [{"d": (r.get("report_date") or "")[-2:],
               "conf": r.get("cumulative_confirmed"),
               "dth": r.get("cumulative_deaths"),
               "cfr": r.get("cfr_pct")} for r in indexed
              if r.get("cumulative_confirmed") is not None]

    def fmt(n):
        return f"{n:,}".replace(",", " ") if isinstance(n, (int, float)) else "-"

    kpi_nums = {
        "confirmed": fmt(latest.get("cumulative_confirmed")),
        "deaths": fmt(latest.get("cumulative_deaths")),
        "cfr": (f"{latest.get('cfr_pct')}%" if latest.get("cfr_pct") is not None else "-"),
        "zones": str(latest.get("health_zones_affected") or "-"),
        "isolation": fmt(latest.get("patients_in_isolation")),
        "hcw": fmt(latest.get("hcw_infected")),
    }

    # Sub-line and secondary-card numbers, derived from the same data. A 24h
    # delta uses the report's own field, or falls back to the change from the
    # previous report; anything we cannot ground stays null and renders as "-".
    prev = indexed[-2] if len(indexed) > 1 else {}

    def delta_24h(field: str, cum_field: str):
        v = latest.get(field)
        if v is not None:
            return v
        a, b = latest.get(cum_field), prev.get(cum_field)
        return a - b if (a is not None and b is not None) else None

    new_conf = delta_24h("new_confirmed_24h", "cumulative_confirmed")
    new_deaths = delta_24h("new_deaths_24h", "cumulative_deaths")

    hcw_inf, hcw_dth = latest.get("hcw_infected"), latest.get("hcw_deaths")
    hcw_cfr = round(hcw_dth / hcw_inf * 100, 1) if (hcw_inf and hcw_dth is not None) else None

    seen, followed = latest.get("contacts_seen"), latest.get("contacts_under_followup")
    contacts_rate = latest.get("contact_followup_rate_pct")
    if contacts_rate is None and followed and seen is not None:
        contacts_rate = round(seen / followed * 100, 1)

    subs = {
        "new_conf_24h": new_conf,
        "new_deaths_24h": new_deaths,
        "zones_total": latest.get("health_zones_total"),
        "hcw_deaths": hcw_dth,
        "hcw_cfr": hcw_cfr,
        "contacts_rate": contacts_rate,
    }
    sec_nums = {
        "new24h": new_conf,
        "suspects": latest.get("suspect_cases_day"),
        "contacts": followed,
        "recovered": latest.get("cumulative_recovered"),
    }

    import json
    prov_path = config.DATASETS_DIR / "province_timeseries.json"
    provinces = []
    if prov_path.exists():
        rows = [r for r in json.loads(prov_path.read_text(encoding="utf-8"))
                if r["sitrep_number"] == latest["sitrep_number"]]
        for r in rows:
            provinces.append({
                "name": r.get("name"), "cases": fmt(r.get("confirmed")),
                "deaths": fmt(r.get("deaths")),
                "cfr": (f"{r.get('cfr_pct')}%" if r.get("cfr_pct") is not None else "-"),
                "zones": (f"{r.get('zones_affected')} / {r.get('zones_total')}"
                          if r.get("zones_affected") is not None else "-"),
                "new24h": str(r.get("new_24h") if r.get("new_24h") is not None else "-"),
            })

    zone_path = config.DATASETS_DIR / "zone_timeseries.json"
    zones = []
    if zone_path.exists():
        prov_code = {"Ituri": "IT", "Nord-Kivu": "NK", "Sud-Kivu": "SK"}
        rows = [r for r in json.loads(zone_path.read_text(encoding="utf-8"))
                if r["sitrep_number"] == latest["sitrep_number"]]
        rows.sort(key=lambda r: r.get("confirmed") or 0, reverse=True)
        for r in rows[:14]:
            zones.append({
                "name": r.get("name"),
                "prov": prov_code.get(r.get("province", ""), "IT"),
                "cases": r.get("confirmed"),
                "cfr": (f"{r.get('cfr_pct')}%" if r.get("cfr_pct") is not None else None),
            })

    return {"sitrep_number": latest["sitrep_number"],
            "report_date": latest.get("report_date"),
            "kpiNums": kpi_nums, "subs": subs, "secNums": sec_nums,
            "series": series, "provinces": provinces, "zones": zones}


@app.get("/api/sitreps")
def sitreps() -> dict:
    import csv

    from src.structured import split_reports
    path = config.DATA_DIR / "sitreps" / "manifest.csv"
    rows = []
    if path.exists():
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
    indexed, holdout = ([], [])
    try:
        indexed, holdout = split_reports()
    except Exception:
        logger.debug("split_reports() unavailable; returning manifest only", exc_info=True)
    return {"reports": rows, "indexed": indexed, "holdout": holdout}


@app.get("/api/datasets/{name}")
def dataset(name: str):
    import json
    p = config.DATASETS_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, f"dataset {name} not found")
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/sitreps/resolve")
def sitreps_resolve(req: IngestUrlRequest) -> dict:
    """Preview a URL: resolve to a PDF link and detect the number/date.

    Lets the front end confirm what will be ingested before committing.
    """
    try:
        from src import uploader
        pdf_url = req.url
        if not uploader.looks_like_pdf_url(req.url):
            pdf_url = uploader.find_pdf_url(req.url)
        return {"pdf_url": pdf_url,
                "number": req.number or uploader.parse_number(req.url, pdf_url),
                "report_date": req.date or uploader.parse_date(req.url, pdf_url)}
    except Exception as e:  # noqa: BLE001
        logger.exception("URL resolve failed for url=%s", req.url)
        raise HTTPException(502, f"Could not resolve URL: {e}") from e


@app.post("/api/sitreps/ingest-url")
def sitreps_ingest_url(req: IngestUrlRequest) -> dict:
    """Ingest a report from a page URL or a direct PDF URL."""
    try:
        from src import uploader
        pdf_bytes, pdf_url = uploader.pdf_from_url(req.url)
        return uploader.add_sitrep(
            pdf_bytes=pdf_bytes, source=req.url, number=req.number,
            date=req.date, pdf_url=pdf_url,
            reextract=req.reextract, reindex=req.reindex)
    except Exception as e:  # noqa: BLE001
        logger.exception("URL ingest failed for url=%s", req.url)
        raise HTTPException(502, f"Ingest failed: {e}") from e


@app.post("/api/sitreps/ingest-file")
def sitreps_ingest_file(
    file: UploadFile = File(...),
    number: int | None = Form(None),
    date: str | None = Form(None),
    reextract: bool = Form(True),
    reindex: bool = Form(True),
) -> dict:
    """Ingest a report from an uploaded PDF file."""
    try:
        from src import uploader
        data = file.file.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(415, "Uploaded file is not a PDF")
        return uploader.add_sitrep(
            pdf_bytes=data, source=file.filename or "", number=number,
            date=date, reextract=reextract, reindex=reindex)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("file ingest failed for filename=%s", file.filename)
        raise HTTPException(502, f"Ingest failed: {e}") from e


# --- Streaming ingest (per-step progress) ----------------------------------
def _ndjson(event: dict) -> str:
    """One NDJSON line the frontend reads to update the progress spinner."""
    import json
    return json.dumps(event) + "\n"


def _stream_ingest(pdf_bytes: bytes, *, source: str, number: int | None,
                   date: str | None, pdf_url: str, reextract: bool, reindex: bool):
    """Yield NDJSON progress events for one ingest, then a final result/error."""
    from src import uploader
    try:
        for ev in uploader.add_sitrep_events(
                pdf_bytes=pdf_bytes, source=source, number=number, date=date,
                pdf_url=pdf_url, reextract=reextract, reindex=reindex):
            yield _ndjson(ev)
    except Exception as e:  # noqa: BLE001 - surface the real reason to the client
        logger.exception("streaming ingest failed for source=%s", source)
        yield _ndjson({"error": str(e)})


@app.post("/api/sitreps/ingest-url-stream")
def sitreps_ingest_url_stream(req: IngestUrlRequest) -> StreamingResponse:
    """Ingest from a URL, streaming a progress event per step as NDJSON."""
    def gen():
        from src import uploader
        yield _ndjson({"step": "download"})
        try:
            pdf_bytes, pdf_url = uploader.pdf_from_url(req.url)
        except Exception as e:  # noqa: BLE001
            logger.exception("URL resolve/download failed for url=%s", req.url)
            yield _ndjson({"error": str(e)})
            return
        yield from _stream_ingest(
            pdf_bytes, source=req.url, number=req.number, date=req.date,
            pdf_url=pdf_url, reextract=req.reextract, reindex=req.reindex)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/sitreps/ingest-file-stream")
def sitreps_ingest_file_stream(
    file: UploadFile = File(...),
    number: int | None = Form(None),
    date: str | None = Form(None),
    reextract: bool = Form(True),
    reindex: bool = Form(True),
) -> StreamingResponse:
    """Ingest an uploaded PDF, streaming a progress event per step as NDJSON."""
    data = file.file.read()
    filename = file.filename or ""

    def gen():
        if not data.startswith(b"%PDF"):
            yield _ndjson({"error": "Uploaded file is not a PDF"})
            return
        yield from _stream_ingest(
            data, source=filename, number=number, date=date,
            pdf_url="", reextract=reextract, reindex=reindex)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/sitreps/{n}/reprocess-stream")
def sitreps_reprocess_stream(n: int) -> StreamingResponse:
    """Re-extract + re-index one archived report, streaming NDJSON progress."""
    from src import uploader
    if uploader._existing_row(n) is None:  # noqa: SLF001 - manifest lookup
        raise HTTPException(404, f"SitRep {n} is not in the library")

    def gen():
        try:
            for ev in uploader.reprocess_events(n):
                yield _ndjson(ev)
        except Exception as e:  # noqa: BLE001
            logger.exception("reprocess failed for n=%s", n)
            yield _ndjson({"error": str(e)})

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    try:
        config.require_keys()
        from src.chat import SitrepChat
        bot = SitrepChat(language=req.lang)
        # Replay prior turns so multi-turn context is preserved across requests.
        for t in req.history:
            bot.history.append({"role": t.role, "content": t.content})
        result = bot.ask(req.message)
    except Exception as e:  # noqa: BLE001
        logger.exception("chat failed for lang=%s", req.lang)
        raise HTTPException(503, f"Chat unavailable: {e}") from e

    # Map any chart spec to the frontend's preset charts when it matches.
    chart = None
    if result.get("charts"):
        spec = result["charts"][0]
        title = (spec.get("title", "") + spec.get("y_label", "")).lower()
        if "letal" in title or "cfr" in title or "fatal" in title:
            chart = "cfr"
        elif "zone" in title:
            chart = "zone"
        else:
            chart = "epi"
    cites = [{"src": f"SitRep N {m['sitrep_number']}", "loc": f"p.{m['page']}"}
             for m in result.get("sources", [])][:4]
    return {"text": result["text"], "cites": cites, "chart": chart}


@app.post("/api/data-quality/assess")
def dq_assess(req: AssessRequest) -> dict:
    """Structured single-report assessment: {score, dimensions, issues, narrative}."""
    try:
        from src import data_quality
        return data_quality.assess_single_structured(req.n, req.lang)
    except Exception as e:  # noqa: BLE001
        logger.exception("assess failed for n=%s lang=%s", req.n, req.lang)
        raise HTTPException(503, f"Assessment unavailable: {e}") from e


@app.post("/api/data-quality/compare")
def dq_compare(req: CompareRequest) -> dict:
    """Structured two-report comparison: {metrics, sections, banner}."""
    try:
        from src import data_quality
        return data_quality.compare_structured(req.a, req.b, req.lang)
    except Exception as e:  # noqa: BLE001
        logger.exception("compare failed for a=%s b=%s lang=%s", req.a, req.b, req.lang)
        raise HTTPException(503, f"Comparison unavailable: {e}") from e


@app.get("/api/topics")
def topics_get() -> dict:
    import json

    from src import topics
    cache = topics.cache_path()
    rows = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []
    return {"rows": rows}


@app.post("/api/topics/run")
def topics_run(lang: str = "fr") -> dict:
    try:
        from src import topics
        rows = topics.run_and_cache(lang)
        return {"rows": rows, "synthesis": topics.synthesise(rows, lang)}
    except Exception as e:  # noqa: BLE001
        logger.exception("topic extraction failed for lang=%s", lang)
        raise HTTPException(503, f"Topic extraction unavailable: {e}") from e


# Static frontend last, so /api/* takes precedence.
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
