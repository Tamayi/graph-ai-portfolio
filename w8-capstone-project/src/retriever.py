"""Retrieval over the Chroma index, plus a structured time-series helper.

`retrieve` powers the chat's RAG context. `load_manifest` and the numeric
helpers feed the charting tools so the assistant can plot trends across the
full series of reports rather than only the few chunks it retrieved.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import chromadb
import voyageai

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

_vo: voyageai.Client | None = None
_coll = None


def _voyage() -> voyageai.Client:
    global _vo
    if _vo is None:
        _vo = voyageai.Client(api_key=config.VOYAGE_API_KEY)
    return _vo


def _collection():
    global _coll
    if _coll is None:
        client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        _coll = client.get_collection(config.COLLECTION_NAME)
    return _coll


def retrieve(query: str, top_k: int | None = None,
             sitrep_numbers: list[int] | None = None) -> list[dict]:
    """Return the most relevant chunks for a query.

    Optionally restrict to specific sitrep numbers (used by the comparison and
    single-report data-quality modules).
    """
    top_k = top_k or config.TOP_K
    qemb = _voyage().embed(
        [query], model=config.VOYAGE_MODEL, input_type="query"
    ).embeddings[0]

    where = None
    if sitrep_numbers:
        where = {"sitrep_number": {"$in": list(sitrep_numbers)}}

    res = _collection().query(
        query_embeddings=[qemb], n_results=top_k, where=where,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0], strict=False
    ):
        out.append({"text": doc, "meta": meta, "score": 1 - dist})
    return out


def format_context(chunks: list[dict]) -> str:
    """Render retrieved chunks as a cited context block for the LLM."""
    parts = []
    for c in chunks:
        m = c["meta"]
        tag = f"[SitRep N°{m['sitrep_number']} | {m['report_date']} | p.{m['page']}]"
        parts.append(f"{tag}\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def load_manifest() -> list[dict]:
    path = config.DATA_DIR / "sitreps" / "manifest.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))
