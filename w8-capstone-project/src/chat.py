"""Multi-turn RAG chat over the sitreps, with a charting tool.

The assistant answers questions grounded in retrieved sitrep chunks and cites
the report number, date and page. When a question calls for a visual (trends,
comparisons), the model calls the `plot_chart` tool; the returned chart spec is
handed back to the UI (Streamlit/Plotly) to render. Conversation history is
passed in by the caller, so multi-turn context is preserved.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import anthropic

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import prompts, retriever, structured  # noqa: E402

logger = logging.getLogger(__name__)

# After a turn completes, stored tool results are truncated to this many
# characters. The model only needs the full payload while answering the
# current turn; a query_data call can return the entire kpi_timeseries JSON,
# which would otherwise be re-sent with every later turn of the session.
TOOL_RESULT_KEEP_CHARS = 600

DATA_TOOL = {
    "name": "query_data",
    "description": (
        "Fetch exact figures from the structured sitrep datasets. Use for "
        "totals, CFR, per-province and per-health-zone case/death counts, and "
        "a single KPI metric over time. More reliable than text for numbers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "enum": ["kpi_timeseries", "metric_series", "zone_table",
                         "pillar_table", "latest"],
                "description": (
                    "kpi_timeseries: all KPIs per report. metric_series: one "
                    "metric over time (set metric). zone_table: per-zone table "
                    "for one report (set sitrep_number, omit for latest). "
                    "pillar_table: a response-pillar table (set pillar to "
                    "laboratory, contacts, ipc or vaccination; optional "
                    "sitrep_number). latest: full record for the latest "
                    "indexed report."),
            },
            "pillar": {
                "type": "string",
                "enum": ["laboratory", "contacts", "ipc", "vaccination"],
                "description": "Which response-pillar table (for pillar_table).",
            },
            "metric": {
                "type": "string",
                "description": (
                    "For metric_series, one of: cumulative_confirmed, "
                    "cumulative_deaths, cfr_pct, new_confirmed_24h, "
                    "health_zones_affected, contacts_under_followup, "
                    "patients_in_isolation, cumulative_recovered."),
            },
            "sitrep_number": {"type": "integer"},
        },
        "required": ["query"],
    },
}


def _run_data_tool(inp: dict):
    q = inp.get("query")
    if q == "kpi_timeseries":
        return structured.kpi_timeseries()
    if q == "metric_series":
        return structured.metric_series(inp.get("metric", ""))
    if q == "zone_table":
        return structured.zone_table(inp.get("sitrep_number"))
    if q == "pillar_table":
        return structured.pillar_table(inp.get("pillar", ""),
                                       inp.get("sitrep_number"))
    if q == "latest":
        return structured.latest()
    return {"error": f"unknown query {q}"}

PLOT_TOOL = {
    "name": "plot_chart",
    "description": (
        "Render a chart for the user. Provide data you extracted from the "
        "SitRep excerpts. Use line for trends over time, bar for comparisons "
        "across reports or health zones, and pie for a single-report breakdown."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": ["line", "bar", "pie"]},
            "title": {"type": "string"},
            "x_label": {"type": "string"},
            "y_label": {"type": "string"},
            "x": {"type": "array", "items": {"type": "string"},
                  "description": "Category or date labels for the x axis."},
            "series": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "y": {"type": "array", "items": {"type": "number"}},
                    },
                    "required": ["name", "y"],
                },
            },
        },
        "required": ["chart_type", "title", "x", "series"],
    },
}


class SitrepChat:
    def __init__(self, language: str = "fr"):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.language = language
        self.history: list[dict] = []   # anthropic message dicts

    def ask(self, question: str, top_k: int | None = None) -> dict:
        """Run one turn. Returns {text, charts:[spec...], sources:[...]}.

        Charts are the inputs of any plot_chart tool calls, ready for Plotly.
        """
        config.require_keys()
        chunks = retriever.retrieve(question, top_k=top_k)
        context = retriever.format_context(chunks)
        user_block = (
            f"Question: {question}\n\n"
            f"SitRep excerpts to use:\n{context}"
        )
        # Remember where this turn starts so it can be compacted once answered.
        turn_start = len(self.history)
        self.history.append({"role": "user", "content": user_block})

        charts: list[dict] = []
        text_parts: list[str] = []

        while True:
            resp = self.client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=1500,
                system=prompts.render("chat_system", lang=self.language),
                tools=[DATA_TOOL, PLOT_TOOL],
                messages=self.history,
                # Auto-cache the prompt prefix (tools + system + history).
                # Cached tokens are re-read at ~0.1x input price, so the
                # second and later iterations of this tool loop, and follow-up
                # turns within the cache TTL, stop paying full price for the
                # whole conversation. Caching silently stays off until the
                # prefix exceeds the model's minimum cacheable size
                # (2048 tokens on Sonnet 4.6).
                cache_control={"type": "ephemeral"},
            )
            # Per-call token accounting: the true request size is the sum of
            # input + cache_read + cache_creation, not input_tokens alone.
            u = resp.usage
            logger.info(
                "chat usage: input=%s output=%s cache_read=%s cache_write=%s",
                u.input_tokens, u.output_tokens,
                getattr(u, "cache_read_input_tokens", 0) or 0,
                getattr(u, "cache_creation_input_tokens", 0) or 0,
            )
            self.history.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            for b in resp.content:
                if b.type == "text":
                    text_parts.append(b.text)

            if not tool_uses:
                break

            tool_results = []
            for tu in tool_uses:
                if tu.name == "plot_chart":
                    charts.append(tu.input)
                    content = "Chart rendered for the user."
                elif tu.name == "query_data":
                    import json as _json
                    content = _json.dumps(_run_data_tool(tu.input),
                                          ensure_ascii=False)
                else:
                    content = "ok"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                })
            self.history.append({"role": "user", "content": tool_results})

        # Compact the finished turn. The retrieved excerpts (~3K tokens) and
        # raw tool payloads were only needed to produce this answer; keeping
        # them would re-send them with every later turn of a session (the
        # Streamlit app reuses this history object across turns). The answer
        # text itself stays, so multi-turn context is preserved.
        self.history[turn_start] = {"role": "user",
                                    "content": f"Question: {question}"}
        for entry in self.history[turn_start + 1:]:
            content = entry.get("content") if isinstance(entry, dict) else None
            if not isinstance(content, list):
                continue  # assistant SDK blocks; only dict tool_results shrink
            for block in content:
                if (isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and isinstance(block.get("content"), str)
                        and len(block["content"]) > TOOL_RESULT_KEEP_CHARS):
                    block["content"] = (
                        block["content"][:TOOL_RESULT_KEEP_CHARS]
                        + " ... [truncated after this turn was answered]")
        return {
            "text": "\n".join(text_parts).strip(),
            "charts": charts,
            "sources": [c["meta"] for c in chunks],
        }
