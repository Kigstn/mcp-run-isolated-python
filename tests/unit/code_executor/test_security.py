import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import textwrap
import threading
import time
import uuid
from pathlib import Path

import pytest

import mcp_run_isolated_python.code_executor as code_executor_module
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


def test_stdin_is_not_inherited(code_executor: CodeExecutor) -> None:
    result, _ = run(code_executor, "import sys; print(repr(sys.stdin.read()))")
    assert result.output == "''"


def test_locked_run_dir_is_removed(code_executor: CodeExecutor) -> None:
    before = set(code_executor.settings.working_directory.iterdir())
    result, _ = run(
        code_executor,
        """
        import os
        os.makedirs("locked/inner")
        open("locked/inner/f", "w").write("x")
        os.chmod("locked/inner", 0)
        os.chmod("locked", 0o500)
        """,
    )
    assert result.status == "success"
    assert set(code_executor.settings.working_directory.iterdir()) == before


def test_total_output_size_is_bounded(code_executor: CodeExecutor, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_executor_module, "MAX_TOTAL_OUTPUT_FILE_BYTES", 2500)
    result, files = run(code_executor, "for i in range(4): open(f'output/f{i}.bin', 'wb').write(b'x' * 1000)")
    assert result.status == "success"
    assert len(files) == 2


def test_deep_directory_tree_is_removed(tmp_path: Path) -> None:
    # sandbox code controls the tree: deeper than PATH_MAX & the fd limit, with a locked leaf
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    fd = os.open(run_dir, os.O_RDONLY)
    for _ in range(2100):
        os.mkdir("d", dir_fd=fd)
        new = os.open("d", os.O_RDONLY, dir_fd=fd)
        os.close(fd)
        fd = new
    os.fchmod(fd, 0)
    os.close(fd)

    code_executor_module._remove_run_dir(run_dir)
    assert not run_dir.exists()


def test_run_waits_for_a_free_slot(code_executor: CodeExecutor, monkeypatch: pytest.MonkeyPatch) -> None:
    slots = threading.Semaphore(0)
    monkeypatch.setattr(code_executor_module, "_run_slots", slots)
    results = []
    waiting = threading.Thread(target=lambda: results.append(run(code_executor, "print(1)")))
    waiting.start()
    time.sleep(1)
    assert results == []  # queued, not rejected

    slots.release()
    waiting.join(timeout=30)
    assert results[0][0].status == "success"
    assert results[0][0].output == "1"
