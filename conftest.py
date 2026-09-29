"""Repo-wide pytest hooks.

Marks tests by directory so ``-m "not integration"`` needs no decorators:
tests/integration -> ``integration``, tests/contract -> ``contract`` (guide section 19).

Hypothesis profiles, chosen with ``HYPOTHESIS_PROFILE``: ``ci`` (the default) is deterministic
and skips the example database, ``dev`` runs fewer examples, and ``nightly`` is random, so each
nightly run tries new inputs. Package conftest files register the same ``ci`` and ``dev``. The
API property tests (tests/contract/test_api_properties.py) run 25 examples per operation, and
200 under ``nightly``.
"""

import os

import pytest
from hypothesis import settings

settings.register_profile(
    "ci", derandomize=True, database=None, max_examples=200, deadline=None, print_blob=True
)
settings.register_profile("dev", database=None, max_examples=50, deadline=None)
settings.register_profile(
    "nightly", database=None, max_examples=200, deadline=None, print_blob=True
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

_MARK_BY_DIR = {"integration": "integration", "contract": "contract"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        parts = item.path.parts
        if "tests" not in parts:
            continue
        index = parts.index("tests") + 1
        kind = parts[index] if index < len(parts) else ""
        mark = _MARK_BY_DIR.get(kind)
        if mark is not None:
            item.add_marker(getattr(pytest.mark, mark))
