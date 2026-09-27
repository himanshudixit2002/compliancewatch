"""Repo-wide pytest hooks.

Marks tests by directory so ``-m "not integration"`` needs no decorators:
tests/integration -> ``integration``, tests/contract -> ``contract`` (guide section 19).
"""

import pytest

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
