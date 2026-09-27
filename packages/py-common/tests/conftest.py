"""Hypothesis profiles, matching the other packages: ``ci`` is deterministic, ``dev`` is quick."""

import os

from hypothesis import settings

settings.register_profile(
    "ci", derandomize=True, database=None, max_examples=200, deadline=None, print_blob=True
)
settings.register_profile("dev", database=None, max_examples=50, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
