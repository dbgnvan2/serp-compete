"""
Pytest configuration for serp-compete tests.

Substitutes a stub for spacy ONLY when the real library is genuinely absent, so
`src.semantic` can still be imported in a bare environment.

The previous version mocked spacy whenever it was not *already* in
`sys.modules`, which was true at collection time even on a machine where spacy
is installed. In a combined run this conftest loads first, so the stub shadowed
the real library for the whole process and
`Serp-compete/tests/test_semantic.py` scored a MagicMock instead of real
tokens — two failures that appeared only when both suites ran together, and
were invisible while the inner suite could not be collected at all.

Prefer the real library; stub only as a fallback.
"""

import sys
from unittest.mock import MagicMock

try:  # pragma: no cover - environment-dependent
    import spacy  # noqa: F401
except ImportError:
    sys.modules["spacy"] = MagicMock()
