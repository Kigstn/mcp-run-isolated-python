import asyncio

from fastmcp import Client

from mcp_run_isolated_python.cli import run


async def test_cli_starts_mcp_server():
    # start server and wait 5s to be up
    process = asyncio.create_task(run())
    await asyncio.sleep(5)

    # test that the MCP server is up by sending a request
    try:
        async with Client("http://localhost:6400/mcp") as client:
            await client.list_tools()

    # stop MCP server
    finally:
        process.cancel()
