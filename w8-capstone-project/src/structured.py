"""Structured "facts" layer over the sitreps.

Most sitreps report the same core tables (header totals, a per-province table,
and a per-health-zone table). This module extracts those into clean JSON so the
app can answer numeric questions (cases per zone, CFR trend, totals) exactly and
instantly, without depending on fuzzy retrieval over messy PDF text. The RAG
text layer still handles narrative and free-text questions.

Design notes:
- Sitreps are dynamic: a given table or column may be absent in some reports.
  Every field is therefore nullable; the extractor must emit null (never guess)
  when a value is not present.
- Extraction is cached per report (datasets/by_report/sitrep_NNN.json), so
  uploading a new sitrep only extracts that one report and then re-aggregates.
- The most recent HOLDOUT_RECENT_N reports are excluded from the app datasets
  and kept as a test set (see split_reports).

Build / refresh:
    python -m src.structured
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import anthropic

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import prompts  # noqa: E402

BY_REPORT_DIR = config.DATASETS_DIR / "by_report"

# Canonical schema. Keep field names stable; add new optional fields rather than
# renaming, so older cached extractions stay compatible.
SCHEMA_FIELDS = {
    "totals": [
        "cumulative_confirmed", "cumulative_deaths", "cfr_pct",
        "new_confirmed_24h", "new_deaths_24h", "health_zones_affected",
        "health_zones_total", "patients_in_isolation", "cumulative_recovered",
        "contacts_under_followup", "contacts_seen", "contact_followup_rate_pct",
        "suspect_cases_day", "hcw_infected", "hcw_deaths",
    ],
    "province": ["name", "confirmed", "deaths", "cfr_pct",
                 "zones_affected", "zones_total", "new_24h"],
    "zone": ["province", "name", "confirmed", "deaths", "cfr_pct"],
    # Response-pillar tables. Frequently present but not guaranteed; vaccination
    # is typically absent in this outbreak (no ring-vaccination campaign is
    # reported) and stays empty until a report includes it.
    "laboratory": ["province", "samples_analysed", "positive", "positivity_pct"],
    "contacts": ["province", "under_followup", "seen", "followup_rate_pct",
                 "newly_listed"],
    "ipc": ["province", "eds_done", "eds_planned", "community_swabs",
            "ess_decontaminated", "households_decontaminated",
            "transports_decontaminated"],
    "vaccination": ["province", "doses_24h", "cumulative_doses",
                    "people_vaccinated", "ring_teams"],
    # Surveillance alert funnel ("Gestion des alertes epidemiologiques").
    "alerts": ["province", "reported_prev_day", "new_alerts", "total_alerts",
               "investigated", "investigation_rate_pct", "validated_alive",
               "validated_dead"],
    # Points of entry / points of control (cross-border screening).
    "poe_poc": ["province", "poc_activated_pct", "travelers", "screened_pct",
                "handwashing_pct", "sensitized_pct", "alerts_notified",
                "alerts_validated_alive", "bodies_intercepted"],
    # Mental health & psychosocial support (SMSPS) beneficiaries.
    "mental_health": ["province", "new_confirmed_supported",
                      "confirmed_followup_supported", "new_suspects_supported",
                      "suspects_followup_supported", "lab_results_announced",
                      "separated_children_supported", "caregivers_supported",
                      "ppl_supported", "community_members_supported",
                      "eds_supported"],
    # Key challenges / impacts / required actions (section "Principaux defis").
    "challenges": ["rank", "challenge", "impact", "action_required"],
}

# Pillar datasets = every SCHEMA_FIELDS table except the three core case tables.
# Each becomes its own <name>_timeseries.json, with sitrep_number/report_date
# stamped on every row so a value can always be traced to its source report.
PILLAR_KEYS = [k for k in SCHEMA_FIELDS if k not in ("totals", "province", "zone")]

# --- Report set / holdout split -------------------------------------------

def _manifest_rows() -> list[dict]:
    path = config.DATA_DIR / "sitreps" / "manifest.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split_reports() -> tuple[list[int], list[int]]:
    """Return (indexed_numbers, holdout_numbers).

    Holdout = the HOLDOUT_RECENT_N reports with the highest numbers.
    """
    nums = sorted(int(r["sitrep_number"]) for r in _manifest_rows())
    if not nums:
        # fall back to scanning markdown files
        nums = sorted(int(re.search(r"sitrep_(\d+)_", p.name).group(1))
                      for p in config.SITREP_MD_DIR.glob("sitrep_*.md"))
    n = config.HOLDOUT_RECENT_N
    holdout = nums[-n:] if n > 0 else []
    indexed = [x for x in nums if x not in holdout]
    return indexed, holdout


def _md_path(num: int) -> Path:
    matches = sorted(config.SITREP_MD_DIR.glob(f"sitrep_{num:03d}_*.md"))
    if not matches:
        raise FileNotFoundError(f"No markdown for SitRep N°{num}")
    return matches[0]


def _meta(num: int) -> str:
    p = _md_path(num)
    m = re.search(r"sitrep_\d+_([0-9-]+)", p.stem)
    return m.group(1) if m else "unknown"


# --- Extraction (LLM) ------------------------------------------------------

def extract_report(num: int, force: bool = False) -> dict:
    """Extract one report to structured JSON, caching the result."""
    BY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cache = BY_REPORT_DIR / f"sitrep_{num:03d}.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))

    config.require_keys()
    date = _meta(num)
    body = _md_path(num).read_text(encoding="utf-8")
    # Retry generously: the request bodies are large (a full report) and can be
    # dropped by flaky networks/proxies, which surfaces as APIConnectionError.
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY,
                                 max_retries=8, timeout=120.0)
    # Generous cap: the schema spans ~11 tables (case tables plus the response
    # pillars and the free-text challenges list), so a full report needs room.
    #
    # Stream the response. A full extraction takes ~60s to generate, and a
    # non-streaming connection is dropped by intermediary proxies once it sits
    # idle that long ("server disconnected without sending a response").
    # Streaming keeps bytes flowing so large responses complete reliably.
    prompt = prompts.render("extract_report", n=num, date=date, body=body)
    chunks: list[str] = []
    with client.messages.stream(
        model=config.ANTHROPIC_MODEL, max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            chunks.append(text)
    raw = "".join(chunks).strip()
    data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    data["sitrep_number"] = num
    data["report_date"] = date
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return data


# --- Aggregation into datasets --------------------------------------------

def build_datasets(include_holdout: bool = False, force: bool = False) -> dict:
    """Extract all (non-holdout) reports and aggregate into dataset JSON files.

    Writes kpi_timeseries.json, province_timeseries.json, zone_timeseries.json,
    one <pillar>_timeseries.json per PILLAR_KEYS entry, and latest.json into
    DATASETS_DIR. Every aggregated row carries sitrep_number and report_date so
    each value is traceable to the report it came from. Returns a small summary.
    """
    indexed, holdout = split_reports()
    targets = indexed + (holdout if include_holdout else [])
    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    kpi, prov, zone = [], [], []
    # Response-pillar tables, each aggregated into its own time series.
    pillars: dict[str, list[dict]] = {k: [] for k in PILLAR_KEYS}
    for num in sorted(targets):
        rec = extract_report(num, force=force)
        meta = {"sitrep_number": num, "report_date": rec.get("report_date")}
        kpi.append({**meta, **(rec.get("totals", {}) or {})})
        for p in rec.get("provinces", []) or []:
            prov.append({**meta, **p})
        for z in rec.get("health_zones", []) or []:
            zone.append({**meta, **z})
        for key in pillars:
            for row in rec.get(key, []) or []:
                pillars[key].append({**meta, **row})

    def _write(name: str, rows: list[dict]) -> None:
        (config.DATASETS_DIR / name).write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    _write("kpi_timeseries.json", kpi)
    _write("province_timeseries.json", prov)
    _write("zone_timeseries.json", zone)
    for key, rows in pillars.items():
        _write(f"{key}_timeseries.json", rows)
    if kpi:
        (config.DATASETS_DIR / "latest.json").write_text(
            json.dumps(extract_report(max(targets)), ensure_ascii=False,
                       indent=1), encoding="utf-8")

    return {"indexed": indexed, "holdout": holdout, "kpi_rows": len(kpi),
            "province_rows": len(prov), "zone_rows": len(zone),
            **{f"{k}_rows": len(v) for k, v in pillars.items()}}


# --- Query helpers (used by the chat's data tool) --------------------------

def _load(name: str):
    p = config.DATASETS_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def kpi_timeseries() -> list[dict]:
    return _load("kpi_timeseries.json")


def metric_series(metric: str) -> list[dict]:
    """Return [{report_date, sitrep_number, value}] for one KPI metric."""
    return [{"sitrep_number": r["sitrep_number"],
             "report_date": r.get("report_date"), "value": r.get(metric)}
            for r in kpi_timeseries() if r.get(metric) is not None]


def zone_table(sitrep_number: int | None = None) -> list[dict]:
    rows = _load("zone_timeseries.json")
    if sitrep_number is None:
        nums = [r["sitrep_number"] for r in rows]
        if not nums:
            return []
        sitrep_number = max(nums)
    return [r for r in rows if r["sitrep_number"] == sitrep_number]


def pillar_table(pillar: str, sitrep_number: int | None = None) -> list[dict]:
    """Return rows for a response-pillar dataset (laboratory, contacts, ipc,
    vaccination). Defaults to the latest report that has rows for that pillar.
    """
    rows = _load(f"{pillar}_timeseries.json")
    if not rows:
        return []
    if sitrep_number is None:
        sitrep_number = max(r["sitrep_number"] for r in rows)
    return [r for r in rows if r["sitrep_number"] == sitrep_number]


def latest() -> dict:
    return json.loads((config.DATASETS_DIR / "latest.json").read_text(
        encoding="utf-8")) if (config.DATASETS_DIR / "latest.json").exists() else {}


if __name__ == "__main__":
    summary = build_datasets()
    print(json.dumps(summary, indent=1))
