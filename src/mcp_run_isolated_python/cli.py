import logging
import subprocess  # noqa: S404
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from mcp_run_isolated_python.log.logger import configure_logging, get_logger
from mcp_run_isolated_python.mcp_server import run_mcp
from mcp_run_isolated_python.utils.settings import Settings

# todo tests


def run(
    path_to_srt_settings: Annotated[
        Path | None,
        "Path to a settings file containing settings for the sandbox environment. View: `https://github.com/anthropic-experimental/sandbox-runtime?tab=readme-ov-file#configuration` for more information. There is a default settings file which will be used otherwise.",
    ] = None,
    python_version: Annotated[
        str,
        "Which python version to use for the virtual environment. Example: `3.13` ",
    ] = "3.13",
    python_dependencies: Annotated[
        list[str] | None,
        "A list of python dependencies to install in the virtual environment. Example: `numpy`",
    ] = None,
    path_to_python: Annotated[
        Path | None,
        "If you already have a python virtual environment set up and want to use that instead of creating a new one, provide the path to the python executable in that virtual environment here. Note: Will overwrite `python_version` and `python_dependencies`. Example: `/path/to/venv/bin/python`",
    ] = None,
    working_directory: Annotated[
        Path | None,
        "The working directory to run the application in. If not provided, the current working directory will be used.",
    ] = None,
    log_level: Annotated[
        int,
        "The log level to use for the application. Example: `logging.INFO -> 20`",
    ] = logging.INFO,
    mcp_transport: Annotated[
        str,
        "Take a look at the FastMCP docs for options.",
    ] = "http",
    mcp_stateless: Annotated[
        bool,
        "Take a look at the FastMCP docs for options.",
    ] = True,
    mcp_port: Annotated[
        int,
        "Take a look at the FastMCP docs for options.",
    ] = 6400,
    mcp_host: Annotated[
        str,
        "Take a look at the FastMCP docs for options.",
    ] = "localhost",
    mcp_path: Annotated[
        str,
        "Take a look at the FastMCP docs for options.",
    ] = "/mcp",
    mcp_code_timeout_seconds: Annotated[
        int,
        "The timeout in seconds for the execution of the python code. If the code takes longer than this to execute, it will be terminated.",
    ] = 30,
):
    """
    Initialise the application by:
    - creating the python interpreter & installing dependencies

    Then, start it.
    """

    if python_dependencies is None:
        python_dependencies = []
    configure_logging(log_level=log_level)
    logger = get_logger(__name__)

    # print banner
    table = Table()
    table.add_column("MCP Run Isolated Python", justify="center", style="bold magenta")
    table.add_row(
        "Thanks for using MCP Run Isolated Python! Please check out the github repo for more information and documentation: https://github.com/Kigstn/mcp-run-isolated-python"
    )
    table.add_row("")
    table.add_row("Starting up the server now... 🚀")

    console = Console(force_terminal=True)
    console.print(table)

    if working_directory is None:
        working_directory = Path.cwd()
    working_directory.mkdir(parents=True, exist_ok=True)

    # create a virtual environment and install dependencies
    if path_to_python is None:
        subprocess.run(["uv", "venv", "--python", python_version], cwd=working_directory, capture_output=True)  # noqa: S603, S607
        if python_dependencies:
            subprocess.run(["uv", "pip", "install", " ".join(python_dependencies)], cwd=working_directory)  # noqa: S603, S607

        path_to_python = working_directory / ".venv" / "bin" / "python"

    # verify that the provided python interpreter works
    else:
        p = subprocess.run([path_to_python, "--version"], cwd=working_directory, capture_output=True)  # noqa: S603
        if p != 0:
            logger.error(f"The provided python interpreter is not working. Please check the path and try again: {p}")
            return

    # verify that the provided settings file exists
    if path_to_srt_settings is None:
        path_to_srt_settings = Path.cwd() / "default_srt_settings.json"
        default_settings_content = path_to_srt_settings.read_text()
        logger.warning(
            f"No settings file provided. Default will be used, make sure this is what you want!\nUsing: {default_settings_content}"
        )

    if not path_to_srt_settings.exists():
        logger.error("The provided path to the settings file does not exist. Please check the path and try again.")
        return

    # start the application
    settings = Settings(
        transport=mcp_transport,
        stateless=mcp_stateless,
        port=mcp_port,
        host=mcp_host,
        path=mcp_path,
        code_timeout_seconds=mcp_code_timeout_seconds,
        path_to_python_interpreter=path_to_python,
        path_to_srt_settings=path_to_srt_settings,
        log_level=log_level,
        installed_python_dependencies=python_dependencies,
        working_directory=working_directory,
    )
    run_mcp(settings=settings)


if __name__ == "__main__":
    typer.run(run)
