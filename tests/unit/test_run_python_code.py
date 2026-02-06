import textwrap

import pytest
from fastmcp import Context

from mcp_run_isolated_python.run_python_code import run_python_code


@pytest.mark.parametrize(
    "code,expected_output",
    [
        pytest.param(
            """
            print("Hello, world!")
            """,
            "Hello, world!",
            id="output is captured",
        ),
        pytest.param(
            """
            print('Hello, world!')
            """,
            "Hello, world!",
            id="output is captured, but different quotes",
        ),
        pytest.param(
            """
            1+1
            """,
            "",
            id="no output is captured when there is no print statement",
        ),
        pytest.param(
            """
            a = 5
            print(a*a)
            """,
            "25",
            id="multiline code",
        ),
        pytest.param(
            """
            import math
            print(math.sqrt(16))
            """,
            "4.0",
            id="imports",
        ),
        pytest.param(
            """
            for i in range(3):
                print(i)
            """,
            "0\n1\n2",
            id="multiple print statements & indentations",
        ),
    ],
)
def test_run_python_code_success(code: str, expected_output: str, mocked_context: Context) -> None:
    code = textwrap.dedent(code).strip()
    response = run_python_code(python_code=code, ctx=mocked_context)

    assert response.status == "success"
    assert response.output == expected_output
    assert response.error is None


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
    ],
)
def test_run_python_code_failure(
    code: str, expected_output: str, expected_partial_error: str, mocked_context: Context
) -> None:
    code = textwrap.dedent(code).strip()
    response = run_python_code(python_code=code, ctx=mocked_context)

    assert response.status == "failure"
    assert response.output == expected_output
    assert isinstance(response.error, str)
    assert expected_partial_error in response.error
