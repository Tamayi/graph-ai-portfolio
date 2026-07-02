"""Central configuration for the BVD/MVE sitrep RAG application.

All settings can be overridden via environment variables (see .env.example).
The defaults are chosen so the app runs locally with a Chroma store on disk.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SITREP_MD_DIR = DATA_DIR / "sitreps" / "md"
SITREP_PDF_DIR = DATA_DIR / "sitreps" / "pdf"
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(DATA_DIR / "chroma")))
DATASETS_DIR = DATA_DIR / "sitreps" / "datasets"   # structured "facts" JSON
PROMPTS_DIR = ROOT / "prompts"                     # externalised LLM prompts

# Optionally hold out the most recent N reports as a test set (0 = disabled).
# The default is disabled: every report in the manifest is extracted and
# indexed. The demo flow instead keeps the most recent reports out of the
# unpacked corpus entirely (scripts/unpack_bundle.py --skip-recent) so the
# user can add them live through the app.
HOLDOUT_RECENT_N = int(os.getenv("HOLDOUT_RECENT_N", "0"))

# --- Models ----------------------------------------------------------------
# Chat / analysis model (Anthropic). claude-sonnet-4-6 is a good quality/cost
# balance; use claude-opus-4-8 for the most demanding comparison tasks.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Voyage embedding model. voyage-4 is multilingual and handles the French
# source text well; voyage-4-lite is cheaper. Both sit inside Voyage's 200M
# token free tier, which far exceeds this corpus (~200K tokens total).
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-4")

# --- Retrieval / chunking --------------------------------------------------
COLLECTION_NAME = "insp_sitreps"
CHUNK_CHARS = 1400          # ~350-400 tokens per chunk
CHUNK_OVERLAP = 200
TOP_K = 8                   # chunks retrieved per query

# --- Keys ------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")

# --- App -------------------------------------------------------------------
SUPPORTED_LANGUAGES = ["fr", "en", "pt"]   # French primary (source language)
DEFAULT_LANGUAGE = "fr"


def require_keys() -> None:
    """Raise a clear error if mandatory API keys are missing."""
    missing = [n for n, v in (("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
                              ("VOYAGE_API_KEY", VOYAGE_API_KEY)) if not v]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): " + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )
