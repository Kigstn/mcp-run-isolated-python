import textwrap
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.tools import Tool

from mcp_run_isolated_python.log.logger import get_logger
from mcp_run_isolated_python.run_python_code import run_python_code
from mcp_run_isolated_python.utils.mcp_context import CustomContext
from mcp_run_isolated_python.utils.settings import Settings

logger = get_logger(__name__)

name = "mcp_run_isolated_python"


def run_mcp(settings: Settings):
    @asynccontextmanager
    async def lifespan(_: FastMCP):
        yield CustomContext(settings=settings)

    mcp = FastMCP[CustomContext](name=name, lifespan=lifespan)
    mcp.add_tool(
        Tool.from_function(
            run_python_code,
            description=textwrap.dedent(f"""
            Tool to execute Python code and return stdout, stderr, and return value.
    
            ### Guidelines
            - The code may be async
            - To output values, you have to use the print statement.
            - You do **not** have any access to the internet
            - The code will be executed with Python 3.13
            - You code must be executed within a timeout. You have {settings.code_timeout_seconds} seconds before the run is canceled.
            - You have these python packages installed: `${settings.python_dependencies}\
            - To output files or images, save them in the "/output_files" folder
            """),
        )
    )

    logger.info(
        f"Starting MCP server `{name}` with transport {settings.transport!r} (Stateless: {settings.stateless}) on http://{settings.host}:{settings.port}{settings.path}"
    )

    mcp.run(
        transport=settings.transport,  # ty:ignore[invalid-argument-type]
        stateless=settings.stateless,
        host=settings.host,
        port=settings.port,
        path=settings.path,
        show_banner=False,
    )


if __name__ == "__main__":
    settings = Settings.from_env_vars()
    run_mcp(settings=settings)
