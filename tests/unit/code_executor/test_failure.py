import os
import textwrap
from unittest import mock
from unittest.mock import MagicMock

import pytest

from mcp_run_isolated_python.code_executor import CodeExecutionResult, CodeExecutor


@pytest.mark.parametrize(
    "code,expected_output,expected_partial_error",
    [
        pytest.param(
            """
            unknown_func()
            """,
            "",
            """NameError: name 'unknown_func' is not defined""",
            id="unknown functions",
        ),
        pytest.param(
            """
            1+1
               print(1)
            """,
            "",
            "IndentationError: unexpected indent",
            id="indentation errors",
        ),
        pytest.param(
            """
            print(1)
            unknown_func()
            """,
            "1",
            """NameError: name 'unknown_func' is not defined""",
            id="in-progress failures with partial output",
        ),
        pytest.param(
            """
            raise ValueError("An error occurred")
            """,
            "",
            """ValueError: An error occurred""",
            id="raises",
        ),
        pytest.param(
            """
            import os
            temp_folder = os.environ.get("RUNNER_TEMP", "/tmp")
            with open(os.path.join(temp_folder, "file.txt"), "w") as f:
                f.write("hi")
            """,
            "",
            "PermissionError: [Errno 1] Operation not permitted",
            id="file write",
        ),
        pytest.param(
            """
            import requests
            requests.get("https://www.google.com")
            """,
            "",
            """OSError: Tunnel connection failed""",
            id="network request",
        ),
    ],
)
def test_failure(code: str, expected_output: str, expected_partial_error: str, code_executor: CodeExecutor) -> None:
    context_mock = MagicMock()

    code = textwrap.dedent(code).strip()
    responses = code_executor.run_python_code(python_code=code, ctx=context_mock)

    # first item is the code execution result, the rest are files
    response = responses.pop(0)
    assert isinstance(response, CodeExecutionResult)
    assert response.status == "failure"
    assert response.output == expected_output
    assert isinstance(response.error, str)
    assert expected_partial_error in response.error

    # check no file responses
    assert len(responses) == 0


def test_env_vars_failure(code_executor: CodeExecutor, monkeypatch: pytest.MonkeyPatch) -> None:
    context_mock = MagicMock()

    with mock.patch.dict(os.environ):
        monkeypatch.setenv("TEST_ENV", "hi")

        code = textwrap.dedent("""
        import os
        print(os.environ["TEST_ENV"])
        """).strip()
        responses = code_executor.run_python_code(python_code=code, ctx=context_mock)

        assert len(responses) == 1
        assert isinstance(responses[0], CodeExecutionResult)
        assert responses[0].status == "failure"
        assert isinstance(responses[0].error, str)
        assert "KeyError: 'TEST_ENV'" in responses[0].error
