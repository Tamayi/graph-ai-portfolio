# BVD/MVE SitRep RAG Application

A retrieval-augmented application over the public situation reports (SitReps)
for the 17th Ebola (Maladie a Virus Ebola / "BVD/MVB") outbreak in the
Democratic Republic of the Congo, published by the Institut National de Sante
Publique (INSP).

It provides three capabilities over the report corpus:

1. A grounded chat assistant that answers questions about case counts, trends
   and outbreak status, cites the source report and page, and can plot charts.
2. AI data-quality assessment of a single report and consistency validation
   between any two reports.
3. Extraction and synthesis of the gaps and challenges (defis / lacunes)
   reported across the series, for public-health analysis.

The UI supports French (primary), English and Portuguese.

## Documentation

- [Data Architecture](https://github.com/Tamayi/graph-ai-portfolio/tree/main/w8-capstone-project/data/) - vectorization pipeline, vector DB recovery, and why data is split between repo and generated artifacts.
- [Technical Guide](docs/SitRep_Technical_Guide.docx) - architecture, data flow and module reference (DOCX).
- [Feature Summary](docs/SitRep_Feature_Summary.docx) - what each screen does, for non-technical readers (DOCX).
- [Intelligence Overview](docs/SitRep_Intelligence_Overview_v3.pptx) - slide-deck walkthrough of the application (PPTX).
- [prompts/](https://github.com/Tamayi/graph-ai-portfolio/tree/main/w8-capstone-project/prompts/) - every LLM prompt lives here as version-controlled Markdown, external to the code so it can be reviewed and edited without changing Python.

## Quickest path to running (Docker)

```
cp .env.example .env               # then add ANTHROPIC_API_KEY and VOYAGE_API_KEY (see API keys below)
docker compose up --build -d       # build the image and serve on :8007
# open http://localhost:8007       # previews with built-in sample data

# build the vector index inside the container (one-time, ~5-10 min):
docker compose exec sitrep python -m src.ingest
```

## Next quickest path to running (local, uv)

```
git clone <repo-url> && cd graph-ai-project

# install uv (https://docs.astral.sh/uv/getting-started/installation/):
#   macOS/Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
#   Windows:      irm https://astral.sh/uv/install.ps1 | iex

uv sync                            # create the venv and install dependencies (uv also fetches Python 3.13)
cp .env.example .env               # then fill in the two keys (see API keys below)
uv run python -m src.ingest        # build the Chroma vector index (~5-10 min, one-time)
uv run main.py                     # serve on http://localhost:8007
```

Markdown SitReps and structured datasets are pre-committed, so you skip unpacking and extraction steps. The vector index builds on first startup.

## Stack

- Anthropic Claude for chat, data-quality and topic analysis
- Voyage AI embeddings (multilingual, handles the French source)
- Chroma as the local vector store
- Streamlit + Plotly front end (reference scaffold; polished UI via Claude Design)

## Data

The source PDFs sit behind a network the build sandbox cannot reach, so the
report text is collected in the browser and exported as a single
`insp_sitreps_bundle.json`. There are 40 distinct reports up to N°042 (INSP's
own numbering skips N°003 and N°029).

**Pre-committed to the repo:**
- `data/sitreps/md/sitrep_*.md` — extracted markdown (already done)
- `data/sitreps/datasets/*.json` — structured tables (already extracted)
- `data/sitreps/manifest.csv` — report registry

**To rebuild from scratch** (e.g., if testing the extraction pipeline):
```bash
uv run scripts/unpack_bundle.py insp_sitreps_bundle.json  # JSON → Markdown
uv run python -m src.structured                          # Extract tables
```

See [data/README.md](data/README.md) for detailed data architecture, vector DB recovery, and why certain artifacts are included/excluded from the repository.

## Structured "facts" Layer

Most sitreps repeat the same core tables (header totals, a per-province table,
a per-health-zone table). `src/structured.py` extracts those into clean JSON
datasets so numeric questions (cases per zone, CFR over time, totals) are
answered exactly and instantly from data, not from fuzzy text retrieval. The
chat exposes a `query_data` tool that reads these datasets first and falls back
to RAG only for narrative questions.

**Pre-generated datasets in `data/sitreps/datasets/`:**
- `kpi_timeseries.json` — case counts, deaths, CFR over time
- `province_timeseries.json` — per-province outbreak metrics
- `zone_timeseries.json` — per-health-zone outbreak metrics
- `latest.json` — most recent report's headline figures
- `laboratory_timeseries.json`, `contacts_timeseries.json`, `ipc_timeseries.json`, `vaccination_timeseries.json` — response pillar timeseries

The chat's `query_data` tool pulls from these for exact answers (lab positivity
by province, contact follow-up rates, IPC/EDS counts, etc.). No fuzzy retrieval
needed for numeric queries.

Sitreps are dynamic, so every field is nullable and the extractor emits null
(never a guess) when a table or column is absent. Extraction is cached per
report, so uploading a new sitrep only extracts that one report and re-builds
the aggregates.

**To re-extract all datasets:**
```bash
uv run python -m src.structured  # regenerate data/sitreps/datasets/*.json
```

Note on vaccination: this outbreak's sitreps do not report an Ebola vaccination
campaign (the only vaccine mentions concern polio and vaccine mistrust), so the
vaccination dataset stays empty. The field exists so that if a future report
adds vaccination figures, they are captured automatically.

## Unseen recent reports

The most recent reports (N°040, 041, 042) are not unpacked from the bundle
(`scripts/unpack_bundle.py --skip-recent`, default 3): they are absent from the
manifest, datasets and index until added live through the app's upload flow
(page URL, PDF URL, or file). This demos ingestion end to end and doubles as an
unseen test set for retrieval and the data-quality comparison.

Setting `HOLDOUT_RECENT_N` (default 0 = disabled) additionally marks the N most
recent manifest reports as a holdout excluded from extraction and indexing.

## Web application (the Claude Design UI)

The approved Claude Design screens are served as the front end from `frontend/`
(the design's HTML plus its `support.js` runtime), wired to a FastAPI backend in
`app/api.py`. The dashboard and chat call the API; if the API is unreachable the
UI falls back to its built-in sample data, so it still previews offline.

### API keys

The live AI features (chat, data quality, topics) and the ingestion/extraction
steps need two keys. Put them in `.env` (copied from `.env.example`).

| Variable | Where to get it | Key format |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic Console, API keys page: https://console.anthropic.com/settings/keys | starts with `sk-ant-api03-` |
| `VOYAGE_API_KEY` | Voyage AI dashboard, API keys page: https://dashboard.voyageai.com/api-keys (dashboard home: https://dashboard.voyageai.com/) | starts with `pa-` |

Notes:
- The Anthropic key must be an API key (`sk-ant-api03-...`), not an OAuth/login
  token (`sk-ant-oat01-...`). The SDK sends it as the `x-api-key` header, and an
  OAuth token there returns `401 invalid x-api-key`.
- Both keys are billable. The test suite mocks these calls, so `uv run pytest`
  stays green without any keys; only the live screens and the pipeline need them.
- `.env` is git-ignored. Never commit it.

```
uv sync                            # create the venv and install dependencies
cp .env.example .env               # then fill in the two keys (see API keys above)
uv run python -m src.ingest        # build the Chroma vector index (one-time, ~5-10 min)
uv run uvicorn app.api:app --reload --port 8007
# open http://localhost:8007
# or simply: uv run main.py
```

**To rebuild from scratch** (testing the extraction/indexing pipeline):
```bash
uv run scripts/unpack_bundle.py insp_sitreps_bundle.json  # extract markdown
uv run python -m src.structured                          # extract tables
uv run python -m src.ingest                              # build vector index
uv run main.py
```

**Optional:** Archive source PDFs locally (for reference):
```bash
uv run scripts/download_pdfs.py    # fetch and archive into data/sitreps/pdf/
```

All six screens are wired to the live backend, in FR/EN/PT, with loading, empty
and error states. The assistant (`/api/chat`) does real multi-turn RAG; the
overview dashboard, KPIs, sub-lines and charts come from `/api/overview`; data
quality (`/api/data-quality/assess` and `/compare`) and topics (`/api/topics`,
`/api/topics/run`) run live and show "run to load" empty states until invoked;
the SitRep library is hydrated from `/api/sitreps`. No synthetic placeholder
data is shown - a field with no value renders as `-`.

### Adding or replacing a SitRep

The SitRep library screen can ingest a new report three ways:

- paste an INSP report page link (e.g. `https://insp.cd/sitrep-n040-mvb_23-06-2026/`)
  and the app finds the PDF link on the page;
- paste a direct PDF link;
- upload a PDF from your computer ("Browse files").

For a link, the app first resolves it (`POST /api/sitreps/resolve`) and shows the
detected PDF, SitRep number and date for you to confirm or correct, then ingests
(`POST /api/sitreps/ingest-url`); uploads go to `POST /api/sitreps/ingest-file`.
Ingestion archives the PDF, extracts its text to markdown, upserts the manifest
(overwriting any existing report with the same number), then re-extracts the
structured facts (Claude) and re-indexes the report (Voyage). Those last two
steps need the API keys; if a key is missing the document is still saved and the
response says extraction was deferred. Text extraction uses PyMuPDF (`pymupdf`),
so scanned image-only PDFs will not yield text (no OCR).

## Project layout

```
config.py                 paths, models, keys, chunking settings
scripts/unpack_bundle.py  bundle JSON -> per-report markdown + manifest
src/ingest.py             chunk + embed (Voyage) + store (Chroma), excl. holdout
src/structured.py         extract core tables to JSON "facts" + holdout split
src/retriever.py          semantic retrieval + manifest helpers
src/chat.py               multi-turn RAG chat with query_data + plot_chart tools
src/data_quality.py       single-report assessment + two-report comparison
src/topics.py             gaps/challenges extraction + synthesis
src/uploader.py           add/replace a SitRep from a page URL, PDF URL or upload
src/i18n.py               FR / EN / PT UI strings
app/api.py                FastAPI backend serving the frontend + API
frontend/index.html       the approved Claude Design screens (wired to the API)
frontend/support.js       the design runtime (renders the screens)
scripts/download_pdfs.py  archive the source PDFs into data/sitreps/pdf/
```

## Notes

- Numbers in answers are grounded in retrieved excerpts and cited; the model is
  instructed never to invent figures.

