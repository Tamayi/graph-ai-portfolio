"""Test setup: make imports work without keys, network, or the heavy stack.

The production modules import anthropic, voyageai and chromadb at module top.
Those are not needed for the tests, which mock every LLM, embedding and vector
call. So when a package is not installed we register a minimal stub for it; when
it is installed, the real one is used unchanged. No test ever reaches the
network, and no API key is required.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _stub(name: str, attrs: list[str]) -> None:
    try:
        __import__(name)
        return
    except Exception:
        pass
    mod = types.ModuleType(name)
    for attr in attrs:
        # A do-nothing callable stands in for the client classes; tests patch the
        # functions that would actually use them, so they are never invoked.
        setattr(mod, attr, type(attr, (), {"__init__": lambda self, *a, **k: None}))
    sys.modules[name] = mod


_stub("anthropic", ["Anthropic"])
_stub("voyageai", ["Client"])
_stub("chromadb", ["PersistentClient"])
