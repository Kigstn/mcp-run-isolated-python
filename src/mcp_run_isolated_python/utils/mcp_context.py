from fastmcp import Context
from pydantic import BaseModel

from mcp_run_isolated_python.utils.settings import Settings


class CustomContext(BaseModel):
    settings: Settings


def get_settings(context: Context) -> Settings:
    return context.request_context.lifespan_context.pool  # ty:ignore[possibly-missing-attribute]
