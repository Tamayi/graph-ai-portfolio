"""Ingestion: read sitrep markdown, chunk, embed with Voyage, store in Chroma.

Run once after unpacking the bundle (and again whenever new sitreps arrive):

    python -m src.ingest

Each chunk keeps metadata (sitrep number, report date, source file, page) so
retrieval results can be cited and filtered, and so the chat can build time
series across reports.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

import chromadb
import voyageai

# Allow running both as `python -m src.ingest` and `python src/ingest.py`.
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

_FNAME_RE = re.compile(r"sitrep_(\d+)_([0-9]{4}-[0-9]{2}-[0-9]{2}|unknown)", re.I)
_PAGE_RE = re.compile(r"^##\s*Page\s+(\d+)", re.I)


def _parse_meta(path: Path) -> tuple[int, str]:
    m = _FNAME_RE.search(path.stem)
    if not m:
        return (-1, "unknown")
    return (int(m.group(1)), m.group(2))


def chunk_markdown(text: str, size: int, overlap: int) -> Iterable[tuple[str, int]]:
    """Yield (chunk_text, page_number) splitting on page markers then size.

    Page markers ("## Page N") let us tag each chunk with its source page so
    citations can point a reader at the exact page of the PDF.
    """
    blocks: list[tuple[str, int]] = []
    cur_page = 1
    buf: list[str] = []
    for line in text.splitlines():
        pm = _PAGE_RE.match(line)
        if pm:
            if buf:
                blocks.append(("\n".join(buf), cur_page))
                buf = []
            cur_page = int(pm.group(1))
            continue
        buf.append(line)
    if buf:
        blocks.append(("\n".join(buf), cur_page))

    for block, page in blocks:
        block = block.strip()
        if not block:
            continue
        if len(block) <= size:
            yield block, page
            continue
        start = 0
        while start < len(block):
            piece = block[start:start + size]
            yield piece.strip(), page
            start += size - overlap


def build_index(reset: bool = True, exclude_holdout: bool = True) -> int:
    config.require_keys()
    md_files = sorted(config.SITREP_MD_DIR.glob("sitrep_*.md"))
    if not md_files:
        raise FileNotFoundError(
            f"No sitrep markdown found in {config.SITREP_MD_DIR}. "
            "Run scripts/unpack_bundle.py first."
        )

    if exclude_holdout:
        # Keep the most recent HOLDOUT_RECENT_N reports out of the index so they
        # can be used as an unseen test set.
        from src.structured import split_reports
        indexed, holdout = split_reports()
        md_files = [p for p in md_files if _parse_meta(p)[0] in set(indexed)]
        print(f"Excluding holdout reports {holdout} from the index")

    vo = voyageai.Client(api_key=config.VOYAGE_API_KEY)
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    if reset:
        try:
            client.delete_collection(config.COLLECTION_NAME)
        except Exception:
            pass
    coll = client.get_or_create_collection(
        config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )

    ids, docs, metas = [], [], []
    for path in md_files:
        num, date = _parse_meta(path)
        text = path.read_text(encoding="utf-8")
        for i, (chunk, page) in enumerate(
            chunk_markdown(text, config.CHUNK_CHARS, config.CHUNK_OVERLAP)
        ):
            ids.append(f"{path.stem}__{i}")
            docs.append(chunk)
            metas.append({
                "sitrep_number": num,
                "report_date": date,
                "page": page,
                "source": path.name,
            })

    # Embed in batches (Voyage accepts up to 128 inputs per call).
    embeddings: list[list[float]] = []
    for start in range(0, len(docs), 128):
        batch = docs[start:start + 128]
        resp = vo.embed(batch, model=config.VOYAGE_MODEL, input_type="document")
        embeddings.extend(resp.embeddings)

    # Add to Chroma in batches.
    for start in range(0, len(docs), 256):
        sl = slice(start, start + 256)
        coll.add(
            ids=ids[sl], documents=docs[sl],
            embeddings=embeddings[sl], metadatas=metas[sl],
        )

    print(f"Indexed {len(docs)} chunks from {len(md_files)} sitreps "
          f"into {config.CHROMA_DIR}")
    return len(docs)


def index_report(num: int) -> int:
    """Embed and (re)index a single report's chunks into Chroma.

    Removes any previously-indexed chunks for the report first, so re-uploading
    a corrected document replaces its chunks rather than duplicating them.
    """
    config.require_keys()
    matches = sorted(config.SITREP_MD_DIR.glob(f"sitrep_{num:03d}_*.md"))
    if not matches:
        raise FileNotFoundError(f"No markdown for SitRep N°{num}")
    path = matches[0]
    _, date = _parse_meta(path)
    text = path.read_text(encoding="utf-8")

    vo = voyageai.Client(api_key=config.VOYAGE_API_KEY)
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    coll = client.get_or_create_collection(
        config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )
    try:
        coll.delete(where={"sitrep_number": num})
    except Exception:  # noqa: BLE001 - nothing indexed yet is fine
        pass

    ids, docs, metas = [], [], []
    for i, (chunk, page) in enumerate(
        chunk_markdown(text, config.CHUNK_CHARS, config.CHUNK_OVERLAP)
    ):
        ids.append(f"{path.stem}__{i}")
        docs.append(chunk)
        metas.append({"sitrep_number": num, "report_date": date,
                      "page": page, "source": path.name})
    if not docs:
        return 0

    embeddings: list[list[float]] = []
    for start in range(0, len(docs), 128):
        resp = vo.embed(docs[start:start + 128], model=config.VOYAGE_MODEL,
                        input_type="document")
        embeddings.extend(resp.embeddings)
    coll.add(ids=ids, documents=docs, embeddings=embeddings, metadatas=metas)
    return len(docs)


if __name__ == "__main__":
    build_index(reset=True)
