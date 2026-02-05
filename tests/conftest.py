from typing import Generator

import pytest


@pytest.fixture(scope="session")
def fixture() -> Generator[str]:
    yield "TODO"
