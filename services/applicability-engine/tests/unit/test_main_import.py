"""Importing the composition root builds no app, so a process that hosts several services can
import every main module and build each app with settings of its own."""

import os
import subprocess
import sys

import pytest

import applicability_engine.main as main

MODULE = "applicability_engine.main"


def test_importing_the_main_module_builds_nothing_and_reads_no_environment() -> None:
    # Production refuses header auth, so settings read from this environment fail to build: an
    # import that built the app would exit with that error.
    environment = {**os.environ, "CW_ENV": "prod", "CW_AUTH_MODE": "header"}
    code = f"import sys, {MODULE} as main; sys.exit(2 if 'app' in vars(main) else 0)"
    finished = subprocess.run(
        [sys.executable, "-c", code], env=environment, capture_output=True, text=True, check=False
    )
    assert finished.returncode == 0, finished.stderr


def test_the_module_offers_build_app_and_no_other_lazy_name() -> None:
    assert callable(main.build_app)
    with pytest.raises(AttributeError, match="has no attribute 'application'"):
        _ = main.application
