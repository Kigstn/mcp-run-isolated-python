from unittest.mock import MagicMock

import pytest
from fastmcp import Context

from mcp_run_isolated_python.utils.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings.using_defaults()


@pytest.fixture
def mocked_context(settings: Settings) -> Context:
    context = MagicMock()
    context.request_context.lifespan_context.pool = settings
    return context
