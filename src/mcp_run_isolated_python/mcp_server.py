import asyncio
import textwrap

from fastmcp import FastMCP
from fastmcp.tools import Tool

from mcp_run_isolated_python.code_executor import CodeExecutor
from mcp_run_isolated_python.utils.logger import get_logger
from mcp_run_isolated_python.utils.settings import FullSettings

logger = get_logger(__name__)

name = "mcp_run_isolated_python"


async def run_mcp(settings: FullSettings):
    mcp = FastMCP(name=name)
    code_executor = CodeExecutor(settings=settings)

    # what python version are we running
    python_version = await asyncio.create_subprocess_shell(
        f"'{settings.path_to_python_interpreter}' --version", stdout=asyncio.subprocess.PIPE
    )
    await python_version.wait()

    mcp.add_tool(
        Tool.from_function(
            code_executor.run_python_code,
            description=textwrap.dedent(f"""
            Tool to execute Python code and return stdout, stderr, and return value.
    
            ### Guidelines
            - The code may be async
            - To output & view values, you have to print them to the console.
            - You do **not** have any access to the internet
            - The code will be executed with {(await python_version.stdout.read()).decode().strip()}
            - Your code is executed within a timeout. You have {settings.code_timeout_seconds} seconds before the run is canceled.
            - You have these additional python packages installed - you cannot install more: `{settings.installed_python_dependencies}`
            - To output files or images, save them in the `./output` folder
            """),  # ty:ignore[unresolved-attribute]
        )
    )

    logger.info(
        f"Starting MCP server `{name}` with transport {settings.transport!r} (Stateless: {settings.stateless}) on http://{settings.host}:{settings.port}{settings.path}"
    )
    logger.info("Streaming logs from the MCP server:")

    await mcp.run_async(
        transport=settings.transport,  # ty:ignore[invalid-argument-type]
        stateless=settings.stateless,
        host=settings.host,
        port=settings.port,
        path=settings.path,
        show_banner=False,
    )


if __name__ == "__main__":
    settings = FullSettings.using_defaults()
    asyncio.run(run_mcp(settings=settings))
