import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp import Client
from pydantic import BaseModel

from mcp_run_isolated_python.run_python_code import CodeExecutionResult


class CodeSandbox(BaseModel):
    client: Client

    async def eval(
        self,
        python_code: str,
    ) -> CodeExecutionResult:
        """
        Run code in the sandbox.
        """
        result = await self.client.call_tool("run_python_code", {"python_code": python_code})
        content_block = result.content[0]
        if content_block.type == "text":
            return json.loads(content_block.text)
        else:
            raise ValueError(f"Unexpected content type: {content_block.type}")


# todo tests
@asynccontextmanager
async def code_sandbox(
    *,
    # todo copy config options over
    dependencies: list[str] | None = None,
) -> AsyncIterator["CodeSandbox"]:
    """
    Create a secure sandbox to execute your python code in.

    It is recommended to **not** use this context manager, but instead host the MCP server in a separate container to avoid potential security issues.
    Please take a look at the github repo for more information: https://github.com/Kigstn/mcp-run-isolated-python
    """

    async with Client("stdio") as client:
        yield CodeSandbox(client=client)
