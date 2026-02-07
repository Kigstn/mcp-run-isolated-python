import pytest

from mcp_run_isolated_python.code_executor import CodeExecutor
from mcp_run_isolated_python.utils.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings.using_defaults()


@pytest.fixture
def code_executor(settings: Settings) -> CodeExecutor:
    code_executor = CodeExecutor(settings=settings)
    return code_executor
