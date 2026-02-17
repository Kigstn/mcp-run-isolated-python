import pytest

from mcp_run_isolated_python.code_executor import CodeExecutor
from mcp_run_isolated_python.utils.settings import Settings


@pytest.fixture
def settings() -> Settings:
    settings = Settings.using_defaults()

    # use a different port for tests to avoid conflicts with a running server
    settings.port += 1

    return settings


@pytest.fixture
def code_executor(settings: Settings) -> CodeExecutor:
    code_executor = CodeExecutor(settings=settings)
    return code_executor
