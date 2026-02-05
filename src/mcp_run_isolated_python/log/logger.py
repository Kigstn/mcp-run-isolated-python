import logging

import fastmcp
import pydantic
import structlog

from mcp_run_isolated_python.log.otel import add_open_telemetry_spans

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
        structlog.processors.StackInfoRenderer(additional_ignores=["log"]),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.PATHNAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            ],
            additional_ignores=["log"],
        ),
        add_open_telemetry_spans,
        structlog.dev.ConsoleRenderer(pad_event_to=60, exception_formatter=exception_formatter),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

_loggers = {}


def get_logger(name: str = "base_logger") -> structlog.BoundLogger:
    if name not in _loggers:
        _loggers[name] = structlog.getLogger(name)

    return _loggers[name]
