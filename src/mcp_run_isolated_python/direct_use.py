import asyncio

from pydantic import BaseModel, PrivateAttr

from mcp_run_isolated_python.code_executor import CodeExecutor, TypeReturnValue
from mcp_run_isolated_python.utils.settings import CodeSandboxSettings


class CodeSandbox(BaseModel):
    """
    A secure sandbox to execute your python code in.

    Usage via async / sync context manager:
    ```python
    from mcp_run_isolated_python import CodeSandbox

    settings = CodeSandboxSettings(...)

    with CodeSandbox(settings=settings) as sandbox:
        result = sandbox.execute("1 + 1")

    async with CodeSandbox(settings=settings) as sandbox:
        result = await sandbox.execute("1 + 1")
    ```
    """

    settings: CodeSandboxSettings

    def __enter__(self) -> "_CodeSandboxSyncClient":
        # initialise
        client = _CodeSandboxSyncClient(settings=self.settings)
        client._prepare()

        return client

    def __exit__(self, *args, **kwargs) -> None:
        return

    async def __aenter__(self) -> "_CodeSandboxAsyncClient":
        # initialise
        client = _CodeSandboxAsyncClient(settings=self.settings)
        await client._prepare()

        return client

    async def __aexit__(self, *args, **kwargs) -> None:
        return


class _CodeSandboxSyncClient(BaseModel):
    settings: CodeSandboxSettings

    _code_executor: CodeExecutor = PrivateAttr()

    def _prepare(self):
        # this runs the pre-check for the SRT CLI tool and ensures it is working correctly before we start executing any code
        self._code_executor = CodeExecutor(settings=self.settings)

    def eval(self, python_code: str) -> TypeReturnValue:
        return self._code_executor.run_python_code(python_code=python_code)


class _CodeSandboxAsyncClient(BaseModel):
    settings: CodeSandboxSettings

    _code_executor: CodeExecutor = PrivateAttr()

    async def _prepare(self):
        # this runs the pre-check for the SRT CLI tool and ensures it is working correctly before we start executing any code
        self._code_executor = await asyncio.to_thread(CodeExecutor, settings=self.settings)

    async def eval(self, python_code: str) -> TypeReturnValue:
        return await asyncio.to_thread(self._code_executor.run_python_code, python_code=python_code)
