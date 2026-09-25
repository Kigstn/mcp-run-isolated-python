import asyncio
import http.client
import textwrap

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.types import EmbeddedResource, TextContent

from mcp_run_isolated_python.code_executor import CodeExecutionResult
from mcp_run_isolated_python.mcp_server import run_mcp
from mcp_run_isolated_python.utils.settings import FullSettings


async def test_start_mcp_server(settings: FullSettings):
    # start server and wait 5s to be up
    process = asyncio.create_task(run_mcp(settings=settings))
    await asyncio.sleep(5)

    # test that the MCP server is up by sending a request
    try:
        async with Client(f"http://localhost:{settings.port}{settings.path}") as client:
            tools = await client.list_tools()
            assert len(tools) == 1

            code = """
            print(123)
            with open("./output/file.txt", "w") as f:
                f.write("hi")
            """
            response = await client.call_tool("run_python_code", {"python_code": textwrap.dedent(code).strip()})

            assert isinstance(response, CallToolResult)
            assert response.is_error is False
            assert isinstance(response.content, list)
            assert len(response.content) == 2

            for content in response.content:
                match content:
                    case TextContent():
                        obj = CodeExecutionResult.model_validate_json(content.text)
                        assert obj.status == "success"
                        assert obj.output == "123"
                        assert obj.error is None
                    case EmbeddedResource():
                        assert content.resource.text == "hi"
                    case _:
                        raise AssertionError(f"Unexpected content type: {type(content)}")

    # stop MCP server
    finally:
        process.cancel()


async def test_foreign_host_header_is_rejected(settings: FullSettings):
    # DNS rebinding: a website resolving its own name to 127.0.0.1 sends its name as Host
    settings.port += 10  # the other server tests may still hold the default test port
    process = asyncio.create_task(run_mcp(settings=settings))
    await asyncio.sleep(5)
    try:

        def post_with_foreign_host() -> int:
            conn = http.client.HTTPConnection("localhost", settings.port, timeout=10)
            conn.request("POST", settings.path, body="{}", headers={"Host": "attacker.example"})
            status = conn.getresponse().status
            conn.close()
            return status

        # in a thread: a blocking request here would block the server running on this event loop
        assert await asyncio.to_thread(post_with_foreign_host) == 421
    finally:
        process.cancel()
