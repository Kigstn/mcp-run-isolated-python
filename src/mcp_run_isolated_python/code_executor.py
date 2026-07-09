import os
import shutil
import subprocess  # noqa: S404
import traceback
import uuid
from typing import Annotated, Any, Literal

from fastmcp.utilities.types import Audio, File, Image
from filetype import guess
from filetype.types import AUDIO, IMAGE
from mcp.types import AudioContent, EmbeddedResource, ImageContent
from pydantic import BaseModel

from mcp_run_isolated_python.utils.logger import get_logger
from mcp_run_isolated_python.utils.settings import CodeSandboxSettings

logger = get_logger(__name__)


class CodeExecutionResult(BaseModel):
    status: Literal["success", "failure"]
    output: str
    error: str | None = None


TypeReturnValue = list[CodeExecutionResult | EmbeddedResource | ImageContent | AudioContent]


class CodeExecutor(BaseModel):
    settings: CodeSandboxSettings

    def model_post_init(self, context: Any, /) -> None:
        logger.info("Pre first run: Running pre-check to verify SRT CLI tool is available and working...")

        # check that it actually works (all deps installed)
        p = subprocess.run(("srt", "-c", "python -c '1+1'"), capture_output=True)
        if p.returncode == 0:
            logger.info("Pre-check for SRT CLI tool succeeded!")
        else:
            logger.error("Pre-check for SRT CLI tool failed", return_code=p.returncode, stderr=p.stderr.decode())
            raise RuntimeError(
                "Pre-check for SRT CLI tool failed. Please install it: `npm install -g @anthropic-ai/sandbox-runtime@'<=0.0.64'` & ensure it is working correctly"
            )

    # Note: This is a sync function on purpose, to avoid the complexity of async subprocess. Uvicorn will spawn this in a thread
    def run_python_code(
        self,
        python_code: Annotated[str, "The python code to execute"],
    ) -> TypeReturnValue:
        try:
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
                    ("srt", "--settings", self.settings.path_to_srt_settings, "-c", cmd),
                    cwd=code_path,
                    capture_output=True,
                    timeout=self.settings.code_timeout_seconds,
                    user=self.settings.user,
                    # limit the env vars, just need path
                    env={"PATH": os.environ.get("PATH", "")},
                )
                logger.info(
                    "Command executed",
                    cmd=cmd,
                    stdout=p.stdout.decode(),
                    stderr=p.stderr.decode(),
                    returncode=p.returncode,
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
                        responses.append(Image(path=file).to_image_content())

                    # is audio?
                    elif type_guess in AUDIO:
                        responses.append(Audio(path=file).to_audio_content())

                    # okay no idea what - normal file it its
                    else:
                        responses.append(File(path=file).to_resource_content())

                # remove temp directory & all files
                shutil.rmtree(code_path)

            return responses
        except Exception:
            logger.exception("Tool run failed")
            return [
                CodeExecutionResult(
                    status="failure",
                    output="Tool run failed. Do not call this tool again, inform the user that it is broken.",
                    error=traceback.format_exc(),
                )
            ]
