from opentelemetry import trace
from structlog.typing import EventDict, ProcessorReturnValue, WrappedLogger


def add_open_telemetry_spans(_: WrappedLogger, __: str, event_dict: EventDict) -> ProcessorReturnValue:
    span = trace.get_current_span()
    if not span.is_recording():
        event_dict["span"] = None
        return event_dict

    ctx = span.get_span_context()
    parent = getattr(span, "parent", None)

    event_dict["span"] = {
        "span_id": format(ctx.span_id, "016x"),
        "trace_id": format(ctx.trace_id, "032x"),
        "parent_span_id": None if not parent else format(parent.span_id, "016x"),
    }

    return event_dict
