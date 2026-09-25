import subprocess  # ruff: ignore[suspicious-subprocess-import]
import textwrap
import time
import uuid
from pathlib import Path

from mcp_run_isolated_python.code_executor import MAX_OUTPUT_BYTES, CodeExecutionResult, CodeExecutor
from mcp_run_isolated_python.utils.settings import FullSettings


def run(code_executor: CodeExecutor, code: str) -> tuple[CodeExecutionResult, list]:
    result, *files = code_executor.run_python_code(python_code=textwrap.dedent(code).strip())
    assert isinstance(result, CodeExecutionResult)
    return result, files


def test_output_symlinks_are_not_followed(code_executor: CodeExecutor, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("server-only")
    result, files = run(
        code_executor,
        f"""
        import os
        os.symlink({str(secret)!r}, "output/leak.txt")
        os.symlink({str(tmp_path)!r}, "output/leak_dir")
        """,
    )
    assert result.status == "success"
    assert files == []


def test_output_dir_symlink_is_not_followed(code_executor: CodeExecutor, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("server-only")
    result, _ = run(
        code_executor,
        f"""
        import os, shutil
        shutil.rmtree("output")
        os.symlink({str(tmp_path)!r}, "output")
        """,
    )
    assert result.status == "failure"
    assert "server-only" not in (result.error or "")


def test_timeout_kills_all_sandboxed_processes(settings: FullSettings) -> None:
    settings.code_timeout_seconds = 2
    marker = f"31.{uuid.uuid4().int % 10**6}"
    result, _ = run(
        CodeExecutor(settings=settings),
        f"""
        import subprocess, time
        subprocess.Popen(["sleep", "{marker}"])
        time.sleep(60)
        """,
    )
    assert result.status == "failure"
    assert "Timed out after 2s" in (result.error or "")
    time.sleep(1)
    processes = subprocess.run(("ps", "-eo", "args"), capture_output=True, text=True, check=True).stdout  # ruff: ignore[start-process-with-partial-path]
    assert f"sleep {marker}" not in processes


def test_output_is_truncated(code_executor: CodeExecutor) -> None:
    result, _ = run(code_executor, f'print("A" * {MAX_OUTPUT_BYTES + 100})')
    assert result.status == "success"
    assert result.output.endswith("[output truncated]")
    assert len(result.output) < MAX_OUTPUT_BYTES + 100


def test_run_dir_is_removed_after_odd_output(code_executor: CodeExecutor) -> None:
    before = set(code_executor.settings.working_directory.iterdir())
    result, files = run(
        code_executor,
        """
        import os, sys
        os.mkdir("output/subdir")
        sys.stdout.buffer.write(b"\\xff")
        """,
    )
    assert result.status == "success"
    assert result.output == "�"
    assert files == []
    assert set(code_executor.settings.working_directory.iterdir()) == before


def test_other_runs_are_not_readable(code_executor: CodeExecutor) -> None:
    other_run = code_executor.settings.working_directory / uuid.uuid4().hex
    other_run.mkdir()
    (other_run / "code.py").write_text("SECRET = 1")
    try:
        result, _ = run(
            code_executor,
            f"""
            import os
            # linux hides other runs, macOS denies listing altogether
            try:
                print({other_run.name!r} in os.listdir(".."))
            except PermissionError:
                print(False)
            open({str(other_run / "code.py")!r}).read()
            """,
        )
    finally:
        (other_run / "code.py").unlink()
        other_run.rmdir()
    assert result.output == "False"
    assert "SECRET" not in (result.error or "")
    assert "Error" in (result.error or "")
