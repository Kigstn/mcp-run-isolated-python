import logging

import aiohttp
import litestar
import numpy
import polars
import pydantic
import whenever
from rich.logging import RichHandler

logging.basicConfig(
    level="NOTSET",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(rich_tracebacks=True, tracebacks_suppress=[aiohttp, polars, pydantic, whenever, numpy, litestar])
    ],
)

_loggers = {}


def get_logger(name: str = "base_logger") -> logging.Logger:
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)

    return _loggers[name]
