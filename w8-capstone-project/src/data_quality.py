"""AI-assisted data-quality assessment of situation reports.

Two modes:
  * assess_single(n)      -> review one SitRep for completeness, internal
                             consistency and arithmetic plausibility.
  * compare(n_a, n_b)     -> validate two SitReps against each other: do
                             cumulative totals move monotonically, are deltas
                             plausible, are there contradictions or omissions.

Both read the full report markdown (not just retrieved chunks) so the model
sees every table, and both return Markdown suitable for direct display.
"""
from __future__ import annotations

import sys
from pathlib import Path

import anthropic

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import prompts  # noqa: E402


def _client() -> anthropic.Anthropic:
    config.require_keys()
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _load(n: int) -> tuple[str, str]:
    """Return (filename, text) for sitrep number n."""
    matches = sorted(config.SITREP_MD_DIR.glob(f"sitrep_{n:03d}_*.md"))
    if not matches:
        raise FileNotFoundError(f"No markdown for SitRep N°{n}")
    p = matches[0]
    return p.name, p.read_text(encoding="utf-8")


def assess_single(n: int, language: str = "fr") -> str:
    fname, body = _load(n)
    msg = _client().messages.create(
        model=config.ANTHROPIC_MODEL, max_tokens=1600,
        messages=[{"role": "user", "content": prompts.render(
            "quality_single", lang=language, fname=fname, body=body)}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def compare(n_a: int, n_b: int, language: str = "fr") -> str:
    fa, a = _load(n_a)
    fb, b = _load(n_b)
    msg = _client().messages.create(
        model=config.ANTHROPIC_MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": prompts.render(
            "quality_compare", lang=language, fa=fa, a=a, fb=fb, b=b)}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


# --- Structured variants ---------------------------------------------------
# The front-end components consume structured JSON (not markdown), so the model
# is forced to call a tool whose input_schema matches the field shapes the UI
# already uses (dims, issuesData, dqScore, dqNarrative; metricsData,
# sectionsData, banner). Every field is nullable: the model must omit or null a
# value it cannot ground in the report rather than guess.

# Quality dimensions and issue categories, kept in lock-step with the front-end
# string keys (S.dim_* and S.cat_*) so the UI can localise them.
DIM_KEYS = ["dim_completeness", "dim_consistency", "dim_timeliness",
            "dim_plausibility", "dim_coverage"]
CAT_KEYS = ["cat_arithmetic", "cat_consistency", "cat_completeness",
            "cat_plausibility", "cat_timeliness", "cat_coverage"]

ASSESS_TOOL = {
    "name": "record_assessment",
    "description": "Record the structured data-quality assessment of one SitRep.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer",
                      "description": "Overall data-quality score, 0 to 100."},
            "dimensions": {
                "type": "array",
                "description": "Score for each quality dimension, 0 to 100.",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": DIM_KEYS},
                        "v": {"type": "integer"},
                    },
                    "required": ["key", "v"],
                },
            },
            "issues": {
                "type": "array",
                "description": "Concrete issues found in the report.",
                "items": {
                    "type": "object",
                    "properties": {
                        "sev": {"type": "string",
                                "enum": ["High", "Medium", "Low"]},
                        "cat": {"type": "string", "enum": CAT_KEYS},
                        "loc": {"type": "string",
                                "description": "Page or section, e.g. p.4."},
                        "text": {"type": "string",
                                 "description": "One sentence, in the requested language."},
                    },
                    "required": ["sev", "cat", "loc", "text"],
                },
            },
            "narrative": {"type": "string",
                          "description": "One or two sentence summary, in the requested language."},
        },
        "required": ["score", "dimensions", "issues", "narrative"],
    },
}

COMPARE_TOOL = {
    "name": "record_comparison",
    "description": "Record the structured consistency comparison of two SitReps.",
    "input_schema": {
        "type": "object",
        "properties": {
            "metrics": {
                "type": "array",
                "description": "One row per shared metric.",
                "items": {
                    "type": "object",
                    "properties": {
                        "m": {"type": "string",
                              "description": "Metric label, in the requested language."},
                        "a": {"type": "string", "description": "Value in report A."},
                        "b": {"type": "string", "description": "Value in report B."},
                        "d": {"type": "string",
                              "description": "Change from A to B, e.g. +109 or -1.2pp."},
                        "flag": {"type": "string",
                                 "enum": ["ok", "warn", "info", "alert"],
                                 "description": "ok plausible, warn check, info neutral, alert contradiction."},
                    },
                    "required": ["m", "a", "b", "d", "flag"],
                },
            },
            "issues": {
                "type": "array",
                "description": "Concrete findings / inconsistencies between the reports.",
                "items": {
                    "type": "object",
                    "properties": {
                        "sev": {"type": "string", "enum": ["High", "Medium", "Low"]},
                        "cat": {"type": "string", "enum": CAT_KEYS},
                        "loc": {"type": "string",
                                "description": "Page or section, e.g. Tableau 1 or p.2."},
                        "text": {"type": "string",
                                 "description": "One sentence, in the requested language."},
                    },
                    "required": ["sev", "cat", "loc", "text"],
                },
            },
            "sections": {
                "type": "array",
                "description": "Notable section-level changes between the reports.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string",
                                 "enum": ["type_added", "type_changed", "type_unchanged"]},
                        "text": {"type": "string",
                                 "description": "One sentence, in the requested language."},
                    },
                    "required": ["type", "text"],
                },
            },
            "banner": {"type": "string",
                       "description": "One-line headline summary, in the requested language."},
        },
        "required": ["metrics", "issues", "sections", "banner"],
    },
}


def _json_via_tool(prompt: str, tool: dict, max_tokens: int = 1800) -> dict:
    """Force the model to return structured data by calling a single tool.

    Raises if the response was cut off at max_tokens: the tool input serializes
    its fields in order, so a truncated call yields a partial dict (e.g. metrics
    present but issues/banner missing) that would silently render as empty. Fail
    loudly instead so the caller can retry with more room rather than show a
    half-filled result.
    """
    # Stream the response: these calls generate thousands of output tokens
    # over a full report (or two), and non-streaming connections that long
    # get dropped mid-request ("Request timed out or interrupted"). Streaming
    # keeps the connection alive; get_final_message() still returns the
    # complete message, so nothing else changes.
    with _client().messages.stream(
        model=config.ANTHROPIC_MODEL, max_tokens=max_tokens,
        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "max_tokens":
        raise RuntimeError(
            f"{tool['name']} output was truncated at max_tokens={max_tokens}; "
            "raise the limit for this call.")
    for block in msg.content:
        if block.type == "tool_use":
            return dict(block.input)
    raise RuntimeError("Model did not return structured output")


def assess_single_structured(n: int, language: str = "fr") -> dict:
    """Single-report assessment as {score, dimensions, issues, narrative}."""
    fname, body = _load(n)
    prompt = prompts.render("quality_single_structured",
                            lang=language, fname=fname, body=body)
    return _json_via_tool(prompt, ASSESS_TOOL, max_tokens=4096)


def compare_structured(n_a: int, n_b: int, language: str = "fr") -> dict:
    """Two-report comparison as {metrics, sections, banner}."""
    fa, a = _load(n_a)
    fb, b = _load(n_b)
    prompt = prompts.render("quality_compare_structured",
                            lang=language, fa=fa, a=a, fb=fb, b=b)
    # The tool input serializes metrics -> issues -> sections -> banner; a tight
    # budget truncates after the metrics array and silently drops the banner and
    # findings, so give the comparison room to emit every field.
    return _json_via_tool(prompt, COMPARE_TOOL, max_tokens=8192)
