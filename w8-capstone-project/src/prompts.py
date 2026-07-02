"""Load LLM prompt templates from the top-level prompts/ directory.

Each prompt lives in its own Markdown file (prompts/<name>.md) so it is easy to
read and edit without touching code. Placeholders use $name / ${name}
(string.Template), so prompt text can contain literal JSON braces { } with no
escaping. Substituted values are inserted verbatim, so a $ in a report body is
harmless.

    from src import prompts
    text = prompts.render("quality_compare", lang="en", fa=fa, a=a, fb=fb, b=b)
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from string import Template

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


@lru_cache(maxsize=None)
def _template(name: str) -> Template:
    path = config.PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"No prompt template: {path}")
    return Template(path.read_text(encoding="utf-8"))


def render(name: str, **values: object) -> str:
    """Render prompt `name`, substituting every $placeholder from `values`.

    Raises KeyError if the template references a placeholder not supplied.
    """
    return _template(name).substitute(**values)
