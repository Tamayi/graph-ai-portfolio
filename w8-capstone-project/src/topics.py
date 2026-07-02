"""Topic extraction and public-health analysis across the sitrep series.

Focus: the "gaps and challenges" (defis / lacunes) that situation reports
record, which are operationally important but scattered across reports. The
module extracts them per report and synthesises recurring themes, returning
both structured JSON (for charts/tables) and a narrative synthesis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import anthropic

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import prompts  # noqa: E402


def _client() -> anthropic.Anthropic:
    config.require_keys()
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _iter_reports():
    import re
    rx = re.compile(r"sitrep_(\d+)_([0-9-]+|unknown)", re.I)
    for p in sorted(config.SITREP_MD_DIR.glob("sitrep_*.md")):
        m = rx.search(p.stem)
        num = int(m.group(1)) if m else -1
        date = m.group(2) if m else "unknown"
        yield num, date, p.read_text(encoding="utf-8")


def extract_all(language: str = "fr") -> list[dict]:
    """Return [{sitrep_number, date, theme, detail}, ...] across all reports."""
    client = _client()
    rows: list[dict] = []
    for num, date, body in _iter_reports():
        msg = client.messages.create(
            model=config.ANTHROPIC_MODEL, max_tokens=1200,
            messages=[{"role": "user", "content": prompts.render(
                "gaps_extract", lang=language, n=num, date=date, body=body)}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        try:
            data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        except Exception:
            data = {"items": []}
        for it in data.get("items", []):
            rows.append({
                "sitrep_number": num, "date": date,
                "theme": it.get("theme", "Autre"),
                "detail": it.get("detail", ""),
            })
    return rows


def synthesise(rows: list[dict], language: str = "fr") -> str:
    msg = _client().messages.create(
        model=config.ANTHROPIC_MODEL, max_tokens=1800,
        messages=[{"role": "user", "content": prompts.render(
            "gaps_synthesise", lang=language,
            items=json.dumps(rows, ensure_ascii=False))}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def cache_path() -> Path:
    return config.DATA_DIR / "sitreps" / "gaps_challenges.json"


def run_and_cache(language: str = "fr") -> list[dict]:
    rows = extract_all(language)
    cache_path().write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows
