"""Archive the source PDFs into data/sitreps/pdf/.

The build sandbox cannot reach insp.cd, so the original PDFs were not downloaded
during ingestion (only their text was extracted). Run this on your own machine,
which can reach insp.cd, to archive the source documents alongside the markdown.

It reads data/sitreps/manifest.csv (which holds each report's pdf_url), downloads
each PDF to data/sitreps/pdf/sitrep_<NNN>_<date>.pdf, skips files already present,
and verifies each download is a real PDF.

Usage:
    python scripts/download_pdfs.py
"""
from __future__ import annotations

import csv
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "sitreps" / "manifest.csv"
PDF_DIR = ROOT / "data" / "sitreps" / "pdf"

UA = "Mozilla/5.0 (sitrep-archiver)"


def encode_url(url: str) -> str:
    """Percent-encode non-ASCII characters (e.g. ``\xb0``) in the URL path/query.

    urllib serialises the request line as ASCII, so a raw degree sign or other
    non-ASCII character in the path raises a UnicodeEncodeError. ``safe="/%"``
    preserves path separators and any already percent-encoded sequences.
    """
    parts = urlsplit(url)
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        quote(parts.path, safe="/%"),
        quote(parts.query, safe="=&%"),
        parts.fragment,
    ))


def main() -> None:
    if not MANIFEST.exists():
        sys.exit(f"Manifest not found: {MANIFEST}. Run unpack_bundle.py first.")
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    ok, skipped, failed = 0, 0, []
    for r in rows:
        num = int(r["sitrep_number"])
        date = r.get("report_date", "unknown")
        url = r.get("pdf_url", "").strip()
        if not url:
            failed.append((num, "no pdf_url"))
            continue
        out = PDF_DIR / f"sitrep_{num:03d}_{date}.pdf"
        if out.exists() and out.stat().st_size > 10_000:
            skipped += 1
            continue
        try:
            req = urllib.request.Request(encode_url(url), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if not data.startswith(b"%PDF"):
                failed.append((num, "not a PDF"))
                continue
            out.write_bytes(data)
            ok += 1
            print(f"  N{num:>3}  {len(data)//1024:>5} KB  {out.name}")
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            failed.append((num, str(e)))

    print(f"\nDownloaded {ok}, skipped {skipped} already present, "
          f"failed {len(failed)}.")
    if failed:
        print("Failed:", failed)


if __name__ == "__main__":
    main()
