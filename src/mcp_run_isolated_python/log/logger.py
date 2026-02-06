import logging

import fastmcp
import pydantic
import structlog

from mcp_run_isolated_python.log.otel import add_open_telemetry_spans


def configure_logging(log_level: int = logging.INFO):
    exception_formatter = structlog.dev.RichTracebackFormatter()
    exception_formatter.width = 180
    exception_formatter.suppress = [pydantic, fastmcp]

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.MaybeTimeStamper(fmt="iso"),
            add_open_telemetry_spans,
            structlog.dev.ConsoleRenderer(pad_event_to=60, exception_formatter=exception_formatter),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


configure_logging()


def get_logger(name: str) -> logging.Logger:
    name = str(name)

    if not name.startswith("mcp_run_isolated_python."):
        name = f"mcp_run_isolated_python.{name}"

    return structlog.getLogger(name)
