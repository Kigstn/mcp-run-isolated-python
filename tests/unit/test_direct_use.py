from mcp_run_isolated_python import CodeExecutionResult, CodeSandbox, TypeReturnValue
from mcp_run_isolated_python.utils.settings import FullSettings


def test_sync_direct_use(settings: FullSettings):
    with CodeSandbox(settings=settings) as sandbox:
        result = sandbox.eval("print(1 + 1)")
        assert_results(result)


async def test_async_direct_use(settings: FullSettings):
    async with CodeSandbox(settings=settings) as sandbox:
        result = await sandbox.eval("print(1 + 1)")
        assert_results(result)


def assert_results(results: TypeReturnValue):
    assert len(results) == 1
    result = results[0]
    assert isinstance(result, CodeExecutionResult)
    assert result.status == "success"
    assert result.output == "2"
    assert result.error is None
