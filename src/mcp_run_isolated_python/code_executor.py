import contextlib
import json
import mimetypes
import os
import pwd
import shutil
import signal
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import threading
import traceback
import uuid
from pathlib import Path
from typing import IO, Annotated, Any, Literal

from fastmcp.utilities.types import Audio, File, Image
from filetype import guess
from filetype.types import AUDIO, IMAGE
from mcp.types import AudioContent, EmbeddedResource, ImageContent
from pydantic import BaseModel, PrivateAttr

from mcp_run_isolated_python.utils.logger import get_logger
from mcp_run_isolated_python.utils.settings import CodeSandboxSettings

logger = get_logger(__name__)

# max bytes kept per stream (stdout / stderr); the rest is drained & dropped
MAX_OUTPUT_BYTES = 1_000_000
# max size of a single returned ./output file; bigger files are skipped
MAX_OUTPUT_FILE_BYTES = 100_000_000
# max total size of all returned ./output files; files past this budget are skipped
MAX_TOTAL_OUTPUT_FILE_BYTES = 200_000_000
# max processes of the sandbox user; keeps a fork bomb from starving the server (shared by concurrent runs)
MAX_SANDBOX_PROCESSES = 256


class CodeExecutionResult(BaseModel):
    status: Literal["success", "failure"]
    output: str
    error: str | None = None


TypeReturnValue = list[CodeExecutionResult | EmbeddedResource | ImageContent | AudioContent]


def _drain(stream: IO[bytes], buf: bytearray) -> None:
    # keep reading so the sandbox never blocks on a full pipe, but only keep MAX_OUTPUT_BYTES (+1 to detect truncation)
    for chunk in iter(lambda: stream.read(65536), b""):
        buf += chunk[: MAX_OUTPUT_BYTES + 1 - len(buf)]


def _decode(buf: bytearray) -> str:
    text = buf[:MAX_OUTPUT_BYTES].decode(errors="replace").strip()
    return text + "\n[output truncated]" if len(buf) > MAX_OUTPUT_BYTES else text


def _remove_run_dir(path: Path) -> None:
    # sandbox code owning its dirs (same-uid mode) can chmod them to block removal: unlock them first.
    # top-down walk unlocks each dir before entering it; symlinks are never chmodded or followed
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRWXU)
    for root, dirs, _ in os.walk(path):
        for name in dirs:
            if not (sub := Path(root) / name).is_symlink():
                with contextlib.suppress(OSError):
                    sub.chmod(stat.S_IRWXU)
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        logger.error("Could not fully remove run directory", path=str(path))


class CodeExecutor(BaseModel):
    settings: CodeSandboxSettings
    _srt_settings: Path = PrivateAttr()

    def _make_run_dir(self, *subdirs: str) -> Path:
        path = self.settings.working_directory / uuid.uuid4().hex
        for subdir in subdirs or ("",):
            (path / subdir).mkdir(parents=True, exist_ok=True)
        # make sure this is owned by the correct user
        if self.settings.user:
            shutil.chown(path, user=self.settings.user)
            for subdir in subdirs:
                shutil.chown(path / subdir, user=self.settings.user)
        return path

    def _write_srt_settings(self) -> None:
        # hide all other runs from the sandbox: deny reading the working directory, but re-allow the run's own
        # directory (the cwd). Written outside the working directory, so sandboxed code can't change it.
        srt_settings = json.loads(self.settings.path_to_srt_settings.read_text())
        fs = srt_settings.setdefault("filesystem", {})
        fs.setdefault("denyRead", []).append(str(self.settings.working_directory.resolve()))
        fs.setdefault("allowRead", []).append(".")
        # srt always makes these writable (shared by all runs & surviving cleanup), so deny them again
        home = Path(pwd.getpwnam(self.settings.user).pw_dir) if self.settings.user else Path.home()
        fs.setdefault("denyWrite", []).extend(
            [
                "/tmp/claude",  # ruff: ignore[hardcoded-temp-file]
                "/private/tmp/claude",
                str(home / ".npm" / "_logs"),
                str(home / ".claude" / "debug"),
            ]
        )
        fd, path = tempfile.mkstemp(prefix="srt-settings-", suffix=".json")

        with os.fdopen(fd, "w") as file:
            json.dump(srt_settings, file)
        Path(path).chmod(0o644)  # the sandbox user must be able to read it
        self._srt_settings = Path(path)

    def model_post_init(self, context: Any, /) -> None:
        logger.info("Pre first run: Running pre-check to verify SRT CLI tool is available and working...")

        # check that it actually works (all deps installed)
        check_path = self._make_run_dir()
        self._write_srt_settings()
        try:
            p = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
                ("srt", "--settings", self._srt_settings, "-c", "true"),  # ruff: ignore[start-process-with-partial-path]
                capture_output=True,
                stdin=subprocess.DEVNULL,
                cwd=check_path,
                check=False,
                user=self.settings.user,
            )
        finally:
            shutil.rmtree(check_path)
        if p.returncode == 0:
            logger.info("Pre-check for SRT CLI tool succeeded!")
        else:
            logger.error("Pre-check for SRT CLI tool failed", return_code=p.returncode, stderr=p.stderr.decode())
            raise RuntimeError(
                "Pre-check for SRT CLI tool failed. Please install it: `npm install -g @anthropic-ai/sandbox-runtime@'<=0.0.64'` & ensure it is working correctly"
            )

    def _run_sandboxed(self, code_path: Path, cmd: str) -> CodeExecutionResult:
        proc = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]
            ("srt", "--settings", self._srt_settings, "-c", cmd),  # ruff: ignore[start-process-with-partial-path]
            cwd=code_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            user=self.settings.user,
            # limit the env vars, just need path (+ keep srt's TMPDIR inside the run dir)
            env={"PATH": os.environ.get("PATH", ""), "CLAUDE_CODE_TMPDIR": str(code_path.resolve())},
            # own process group, so a timeout can kill the whole sandbox & not just srt
            start_new_session=True,
        )
        stdout, stderr = bytearray(), bytearray()
        readers = [
            threading.Thread(target=_drain, args=(proc.stdout, stdout), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            proc.wait(timeout=self.settings.code_timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            # kills srt + outer bwrap; the inner bwrap (own session) dies with its parent (--die-with-parent)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        for reader in readers:
            reader.join(timeout=5)

        result = CodeExecutionResult(
            status="success" if proc.returncode == 0 and not timed_out else "failure",
            output=_decode(stdout),
            error=_decode(stderr) or None,
        )
        if timed_out:
            result.error = f"{result.error or ''}\nTimed out after {self.settings.code_timeout_seconds}s".strip()
        logger.info("Command executed", cmd=cmd, result=result.model_dump(), returncode=proc.returncode)
        return result

    @staticmethod
    def _collect_output_files(output_path: Path) -> TypeReturnValue:
        # the output dir is writable by the sandbox: never follow symlinks (could point at files only the server
        # can read) & only return regular, not hard-linked files of bounded size
        responses: TypeReturnValue = []
        total = 0
        dir_fd = os.open(output_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for name in os.listdir(dir_fd):  # ruff: ignore[os-listdir]  (fd-based: iterdir would follow a symlinked dir)
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
                except OSError:
                    logger.warning("Skipping output entry that can't be opened (e.g. symlink)", name=name)
                    continue
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                    os.close(fd)
                    logger.warning("Skipping output entry that is not a regular file", name=name)
                    continue
                with os.fdopen(fd, "rb") as file:
                    data = file.read(MAX_OUTPUT_FILE_BYTES + 1)
                if len(data) > MAX_OUTPUT_FILE_BYTES or total + len(data) > MAX_TOTAL_OUTPUT_FILE_BYTES:
                    logger.warning("Skipping output file that is too big", name=name)
                    continue
                total += len(data)

                type_guess = guess(data)

                # is image?
                if type_guess in IMAGE:
                    responses.append(Image(data=data, format=type_guess.mime.split("/")[1]).to_image_content())

                # is audio?
                elif type_guess in AUDIO:
                    responses.append(Audio(data=data, format=type_guess.extension).to_audio_content())

                # okay no idea what - normal file it its
                else:
                    mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    responses.append(File(data=data, name=name).to_resource_content(mime_type=mime_type))
        finally:
            os.close(dir_fd)
        return responses

    # Note: This is a sync function on purpose, to avoid the complexity of async subprocess. Uvicorn will spawn this in a thread
    def run_python_code(
        self,
        python_code: Annotated[str, "The python code to execute"],
    ) -> TypeReturnValue:
        code_path = None
        try:
            # create a temp working dir for the code to have write perms in
            code_path = self._make_run_dir("output")

            # write the code to a temp file
            code_file_path = code_path / "code.py"
            with code_file_path.open("w") as file:
                file.write(python_code)

            # run the code
            logger.info("Running python code...", code=python_code, settings=self.settings.model_dump())
            # best-effort limits (a lower hard limit is kept); on linux, a fresh ipc namespace per run
            limits = (
                f"ulimit -u {MAX_SANDBOX_PROCESSES} 2>/dev/null; ulimit -f {MAX_OUTPUT_FILE_BYTES // 1024} 2>/dev/null"
            )
            ipc = (
                "unshare --ipc --user --map-current-user "
                if sys.platform == "linux" and shutil.which("unshare")
                else ""
            )
            cmd = f"""{limits}; exec {ipc}"{self.settings.path_to_python_interpreter}" "{code_file_path}" """
            result = self._run_sandboxed(code_path, cmd)

            # return output files
            return [result, *self._collect_output_files(code_path / "output")]
        except Exception:
            logger.exception("Tool run failed")
            return [
                CodeExecutionResult(
                    status="failure",
                    output="Tool run failed. Do not call this tool again, inform the user that it is broken.",
                    error=traceback.format_exc(),
                )
            ]
        finally:
            # remove temp directory & all files, also when the run failed
            if code_path is not None:
                _remove_run_dir(code_path)
