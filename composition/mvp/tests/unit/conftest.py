"""The combined app on memory stores, built once for the tests that only read its routes."""

import pytest

from cw_mvp.app import CombinedApp, build_app
from cw_mvp.testing import MEMORY_SERVICES, mvp_settings


@pytest.fixture(scope="session")
def memory_app() -> CombinedApp:
    return build_app(mvp_settings(log_level="WARNING"), service_overrides=MEMORY_SERVICES)
