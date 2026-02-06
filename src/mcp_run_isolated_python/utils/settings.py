import logging
import os
from typing import Self

from pydantic import BaseModel, Field


class Settings(BaseModel):
    transport: str = "http"
    stateless: bool = True
    port: int = 6400
    host: str = "localhost"
    path: str = "/mcp"
    log_level: int = logging.INFO

    code_timeout_seconds: int = 30
    python_dependencies: list[str] = Field(default_factory=list)
    path_to_python_interpreter: str = ""

    @classmethod
    def from_env_vars(cls) -> Self:
        env_vars = {}
        for field in cls.model_fields:
            if env := os.getenv(f"MCP_RUN_ISOLATED_PYTHON_{field}".upper()):
                env_vars[field] = env
        return cls(**env_vars)
