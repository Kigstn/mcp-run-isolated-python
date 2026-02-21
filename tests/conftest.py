import pytest

from mcp_run_isolated_python.code_executor import CodeExecutor
from mcp_run_isolated_python.utils.settings import FullSettings


@pytest.fixture
def settings() -> FullSettings:
    settings = FullSettings.using_defaults()

    # use a different port for tests to avoid conflicts with a running server
    settings.port += 1

    return settings


@pytest.fixture
def code_executor(settings: FullSettings) -> CodeExecutor:
    code_executor = CodeExecutor(settings=settings)
    return code_executor
