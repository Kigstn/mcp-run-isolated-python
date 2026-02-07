import os
import shutil
import subprocess  # noqa: S404
import sys
import uuid
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.utilities.types import Audio, File, Image
from filetype import guess
from filetype.types import AUDIO, IMAGE
from pydantic import BaseModel, PrivateAttr

from mcp_run_isolated_python.utils.logger import get_logger
from mcp_run_isolated_python.utils.settings import Settings

logger = get_logger(__name__)


class CodeExecutionResult(BaseModel):
    status: Literal["success", "failure"]
    output: str
    error: str | None = None


class CodeExecutor(BaseModel):
    settings: Settings

    _pre_check_succeeded: bool | None = PrivateAttr(None)

    def run_python_code(
        self,
        python_code: Annotated[str, "The python code to execute"],
        ctx: Context,
    ) -> list[CodeExecutionResult | File | Image | Audio]:
        if self._pre_check_succeeded is None:
            logger.info("First run: Running pre-check to verify SRT CLI tool is available and working...")

            # check that it actually works (all deps installed)
            p = subprocess.run(("srt", "python -c '1+1'"), capture_output=True)

            # only run this once
            self._pre_check_succeeded = p.returncode == 0
            if self._pre_check_succeeded:
                logger.info("Pre-check for SRT CLI tool succeeded!")
            else:
                logger.error("Pre-check for SRT CLI tool failed", return_code=p.returncode, stderr=p.stderr.decode())
                sys.exit(1)

        if not self._pre_check_succeeded:
            raise RuntimeError(
                "Pre-check for SRT CLI tool failed. Please install it: `npm install -g @anthropic-ai/sandbox-runtime` & ensure it is working correctly"
            )

        # create a temp working dir for the code to have write perms in
        code_path = self.settings.working_directory / uuid.uuid4().hex
        (code_path / "output").mkdir(parents=True)

        # write the code to a temp file
        code_file_path = code_path / "code.py"
        with code_file_path.open("w") as file:
            file.write(python_code)

        # run the code
        logger.info("Running python code...", code=python_code, settings=self.settings.model_dump())
        try:
            cmd = f""""{self.settings.path_to_python_interpreter}" "{code_file_path}" """
            p = subprocess.run(  # noqa: S603
                ("srt", "--settings", self.settings.path_to_srt_settings, cmd),
                cwd=code_path,
                capture_output=True,
                timeout=self.settings.code_timeout_seconds,
                # limit the env vars, just need path
                env={"PATH": os.environ.get("PATH", "")},
            )
            logger.info(
                "Command executed", cmd=cmd, stdout=p.stdout.decode(), stderr=p.stderr.decode(), returncode=p.returncode
            )
        finally:
            responses = [
                CodeExecutionResult(
                    status="success" if p.returncode == 0 else "failure",
                    output=p.stdout.decode().strip(),
                    error=p.stderr.decode().strip() if p.stderr else None,
                )
            ]

            # return output files
            for file in (code_path / "output").iterdir():
                type_guess = guess(file)

                # is image?
                if type_guess in IMAGE:
                    responses.append(Image(path=file))

                # is audio?
                elif type_guess in AUDIO:
                    responses.append(Audio(path=file))

                # okay no idea what - normal file it its
                else:
                    responses.append(File(path=file))

            # remove temp directory & all files
            shutil.rmtree(code_path)

        return responses
