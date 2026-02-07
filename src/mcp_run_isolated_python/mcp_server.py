import textwrap

from fastmcp import FastMCP
from fastmcp.tools import Tool

from mcp_run_isolated_python.code_executor import CodeExecutor
from mcp_run_isolated_python.utils.logger import get_logger
from mcp_run_isolated_python.utils.settings import Settings

logger = get_logger(__name__)

name = "mcp_run_isolated_python"

# todo tests


def run_mcp(settings: Settings):
    mcp = FastMCP(name=name)
    code_executor = CodeExecutor(settings=settings)

    mcp.add_tool(
        Tool.from_function(
            code_executor.run_python_code,
            description=textwrap.dedent(f"""
            Tool to execute Python code and return stdout, stderr, and return value.
    
            ### Guidelines
            - The code may be async
            - To output values, you have to use the print statement.
            - You do **not** have any access to the internet
            - The code will be executed with Python 3.13
            - You code must be executed within a timeout. You have {settings.code_timeout_seconds} seconds before the run is canceled.
            - You have these additional python packages installed: `${settings.installed_python_dependencies}\
            - To output files or images, save them in the "./output" folder
            """),
        )
    )

    logger.info(
        f"Starting MCP server `{name}` with transport {settings.transport!r} (Stateless: {settings.stateless}) on http://{settings.host}:{settings.port}{settings.path}"
    )
    logger.info("Streaming logs from the MCP server:")

    mcp.run(
        transport=settings.transport,  # ty:ignore[invalid-argument-type]
        stateless=settings.stateless,
        host=settings.host,
        port=settings.port,
        path=settings.path,
        show_banner=False,
    )


if __name__ == "__main__":
    settings = Settings.using_defaults()
    run_mcp(settings=settings)
