"""Unpack the sitrep bundle exported from the browser into per-report files.

The browser extraction step produces a single `insp_sitreps_bundle.json`
containing the markdown text of every situation report (the source PDFs are
behind a network the local sandbox cannot reach, so text is carried in JSON).

Usage:
    python scripts/unpack_bundle.py path/to/insp_sitreps_bundle.json [--skip-recent N]

The most recent N reports (default 3) are NOT unpacked: they stay out of the
corpus so they can be added live through the app's upload flow. Pass
--skip-recent 0 to unpack everything.

This writes:
    data/sitreps/md/sitrep_<NNN>_<YYYY-MM-DD>.md   (one per report)
    data/sitreps/manifest.csv                       (index of all reports)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD_DIR = ROOT / "data" / "sitreps" / "md"
MANIFEST = ROOT / "data" / "sitreps" / "manifest.csv"


def main(bundle_path: str, skip_recent: int = 3) -> None:
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    sitreps = bundle.get("sitreps", {})
    MD_DIR.mkdir(parents=True, exist_ok=True)

    keys = sorted(sitreps, key=lambda k: int(sitreps[k]["number"]))
    if skip_recent > 0:
        skipped = [int(sitreps[k]["number"]) for k in keys[-skip_recent:]]
        keys = keys[:-skip_recent]
        print(f"Skipping the {skip_recent} most recent reports {skipped}; "
              "add them through the app to demo ingestion.")

    rows = []
    for key in keys:
        s = sitreps[key]
        num = int(s["number"])
        date = (s.get("date") or "unknown")
        fname = f"sitrep_{num:03d}_{date}.md"
        (MD_DIR / fname).write_text(s["markdown"], encoding="utf-8")
        rows.append({
            "sitrep_number": num,
            "report_date": date,
            "title": s.get("title", ""),
            "pdf_url": s.get("pdf_url", ""),
            "md_filename": fname,
            "chars": len(s["markdown"]),
        })

    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} markdown files to {MD_DIR}")
    print(f"Manifest: {MANIFEST}")


if __name__ == "__main__":
    args = sys.argv[1:]
    skip = 3
    if "--skip-recent" in args:
        i = args.index("--skip-recent")
        skip = int(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    main(args[0], skip_recent=skip)
