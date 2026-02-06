import textwrap
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastmcp.utilities.types import Audio, File, Image

from mcp_run_isolated_python.run_python_code import CodeExecutionResult, CodeExecutor


@pytest.mark.parametrize(
    "code,expected_output,expected_file_data",
    [
        pytest.param(
            """
            print("Hello, world!")
            """,
            "Hello, world!",
            [],
            id="output is captured",
        ),
        pytest.param(
            """
            print('Hello, world!')
            """,
            "Hello, world!",
            [],
            id="output is captured, but different quotes",
        ),
        pytest.param(
            """
            1+1
            """,
            "",
            [],
            id="no output is captured when there is no print statement",
        ),
        pytest.param(
            """
            a = 5
            print(a*a)
            """,
            "25",
            [],
            id="multiline code",
        ),
        pytest.param(
            """
            import math
            print(math.sqrt(16))
            """,
            "4.0",
            [],
            id="imports",
        ),
        pytest.param(
            """
            for i in range(3):
                print(i)
            """,
            "0\n1\n2",
            [],
            id="multiple print statements & indentations",
        ),
        pytest.param(
            """
            with open("./file.txt", "w") as f:
                f.write("hi")
            """,
            "",
            [],
            id="file write - wrong folder",
        ),
        pytest.param(
            """
            with open("./output/file.txt", "w") as f:
                f.write("hi")
            """,
            "",
            [
                {
                    "type": File,
                    "mime": "text/plain",
                }
            ],
            id="file write - file",
        ),
        pytest.param(
            """
            with open("./output/file1.txt", "w") as f:
                f.write("hi")
            with open("./output/file2.txt", "w") as f:
                f.write("bye")
            """,
            "",
            [
                {
                    "type": File,
                    "mime": "text/plain",
                },
                {
                    "type": File,
                    "mime": "text/plain",
                },
            ],
            id="file write - two files",
        ),
        pytest.param(
            """
            header = b"ID3" + bytes([0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            with open("./output/file.mp3", "wb") as f:
                f.write(header)
            """,
            "",
            [
                {
                    "type": Audio,
                    "mime": "audio/mpeg",
                }
            ],
            id="file write - audio",
        ),
        pytest.param(
            """
            import base64
            png_b64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAeCAYAAABNChwpAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAACQAAAAAQAAAJAAAAABAAKgAgAEAAAAAQAAACCgAwAEAAAAAQAAAB4AAAAA2L2NEgAAAAlwSFlzAAAWJQAAFiUBSVIk8AAAA25JREFUSA1d1gtu6zAMRNHESfe/0m6gvzwfIjchHgFFIjkzJGW76PXz8/Nxu90uj8fjchzHLGeW7/z393e53++Ol9/f38vHx8eLI0fDfr1eZ/HhWLF0xZzFzxrHAGuASIJiicKxxMY5fxLacbHv7+/JNdzWwi1+6BKZ1bFiCKwGnYs1rZgGmZxFSx7PmWZ4NyjWMINDjpRQMTtwqyJ2MTsR1iANEZZ21u3KhTsAShDb/gbC8Ms7w9utmpTPd7Z+fn7m/YHJxNm9gwJdVwJ2JldzfFcp95rieUsKwcFnzgrD1pBcsbkBCQFkQOLEai5RGIJyMOJirOZ3U+VhrJqApzN1Ba2mlQQ25Z5ErAmbZAviF1eY+RJg6Fg0WINNneniTNgVENxgwi0YZwXawyYqLsZoha2OHExar7dCEEHCarpiCRGW2zuuxeArMIHnj8J4NVWdAzhByd09UB0nyt/N9G2rQyc+Lj2GC9eZnw0iYGRJZ2s3tZuAkfPYmozvTzTDFZfXTNZQdnrzFTRRBWooYn7T8hPC7azoLrgb8kJmOLBsbqAJaqTJATTVaio+UyCuJvBrNow862bSCncQFQSsKwRnoq2ITQsjtvM4Fi1xRWBqVCxOekddSzJ+e90TJSJXwQGdP4Rcu515TGni8/ErDBOW1p3zf6dAjFDF+QRha7YdrgK9A90CPsNrF2uQeQQFKlYRoJojWBE4K+tsh+mm5MvRocGv+HOg90QCGaEEkfsCasoOsxsTg0sn374L58+j4hBiyM5iDKlVvOfdteM4K1oRXBpiNYjfzYh1s3cOEbYFprtzcrFyxYjh8RmfoKK+95f4Uzc+rRqxD6+pgQgCEW8RrVBC9j0hbNYwmnBbDZAGnpidzQ04ADRVE+iwrusYcTp/ToybWPj8rQMn35DOcCfm/RIKdAPOCdn7N9wZJ3OuybRg9rvC3zzn7PUfkQCBpiPKekQVEYPpEdmbBmbzTCvHwvOLTVM6ZYJAFayZ8jAIkeUtRSzGb6cVF0cOv+kb6Iy/r5NQVzdK508khLAEK6pQk9vh7fJxKyrWAPFfDQARUyRi09SMfLmvr68JJ+7malBiN9O5ZsNNvYpWRFKXbqKm+ArUNR/OqqHE0wkj76yJOPn05iVEZhJsEqc4Q2I9mqYRc96+WDdil2PpbXy4fyD+UYfepcB7AAAAAElFTkSuQmCC"           
            with open("./output/file.png", "wb") as f:
                f.write(base64.b64decode(png_b64))
            """,
            "",
            [
                {
                    "type": Image,
                    "mime": "image/png",
                }
            ],
            id="file write - image",
        ),
    ],
)
def test_run_python_code_success(
    code: str, expected_output: str, expected_file_data: list[dict[str, Any]], code_executor: CodeExecutor
) -> None:
    context_mock = MagicMock()

    code = textwrap.dedent(code).strip()
    responses = code_executor.run_python_code(python_code=code, ctx=context_mock)

    # first item is the code execution result, the rest are files
    response = responses.pop(0)
    assert isinstance(response, CodeExecutionResult)
    assert response.status == "success"
    assert response.output == expected_output
    assert response.error is None

    # check the file
    assert len(responses) == len(expected_file_data)
    for file_response, expected_data in zip(responses, expected_file_data, strict=False):
        assert isinstance(file_response, expected_data["type"])
        assert file_response._mime_type == expected_data["mime"]


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
            with open("/file.txt", "w") as f:
                f.write("hi")
            """,
            "",
            """PermissionError: [Errno 1] Operation not permitted""",
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
def test_run_python_code_failure(
    code: str, expected_output: str, expected_partial_error: str, code_executor: CodeExecutor
) -> None:
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

    # check the file
    for _file_response in responses:
        pass
