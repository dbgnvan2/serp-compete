"""
Pytest configuration for serp-compete tests.

Mocks spacy at the module level so tests can import src.semantic (which imports spacy)
without requiring spacy to be installed. The mock only takes effect if spacy hasn't
already been loaded into the process.
"""

import sys
from unittest.mock import MagicMock

if "spacy" not in sys.modules:
    sys.modules["spacy"] = MagicMock()
