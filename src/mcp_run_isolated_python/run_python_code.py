import subprocess  # noqa: S404
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import Context
from pydantic import BaseModel

from mcp_run_isolated_python.log.logger import get_logger
from mcp_run_isolated_python.utils.mcp_context import get_settings

logger = get_logger(__name__)

py_executable = "/Users/daniel.jaekel/PycharmProjects/NonVodafone/mcp-run-isolated-python/.venv/bin/python"

_pre_check_succeeded: bool | None = None


class CodeExecutionResult(BaseModel):
    status: Literal["success", "failure"]
    output: str
    error: str | None = None


def run_python_code(
    python_code: Annotated[str, "The python code to execute"],
    ctx: Context,
) -> CodeExecutionResult:
    global _pre_check_succeeded

    settings = get_settings(context=ctx)

    if _pre_check_succeeded is None:
        logger.info("First run: Running pre-check to verify SRT CLI tool is available and working...")
        p = subprocess.run(("srt", "python -c '1+1'"), capture_output=True)
        _pre_check_succeeded = p.returncode == 0
        if _pre_check_succeeded:
            logger.info("Pre-check for SRT CLI tool succeeded!")
        else:
            logger.error(f"Pre-check for SRT CLI tool failed with return code {p.returncode} and error: {p.stderr}")

    if not _pre_check_succeeded:
        raise RuntimeError(
            "Pre-check for SRT CLI tool failed. Please install it: `npm install -g @anthropic-ai/sandbox-runtime` & ensure it is working correctly"
        )

    logger.info("Running python code...")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as file:
        file.write(python_code)
        path = Path(file.name)

    try:
        cmd = f""""{py_executable}" "{path}" """
        p = subprocess.run(("srt", cmd), cwd=".", capture_output=True, timeout=settings.code_timeout_seconds)  # noqa: S603
    finally:
        # remove file always
        path.unlink()

    return CodeExecutionResult(
        status="success" if p.returncode == 0 else "failure",
        output=p.stdout.decode().strip(),
        error=p.stderr.decode() if p.stderr else None,
    )
