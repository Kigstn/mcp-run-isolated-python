import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator


class Settings(BaseModel):
    transport: str
    stateless: bool
    port: int
    host: str
    path: str
    code_timeout_seconds: int

    log_level: int
    path_to_python_interpreter: Path
    path_to_srt_settings: Path

    installed_python_dependencies: list[str] = Field(default_factory=list)

    @classmethod
    def using_defaults(cls) -> "Settings":
        return cls(
            transport="http",
            stateless=True,
            port=6400,
            host="localhost",
            path="/mcp",
            log_level=logging.INFO,
            code_timeout_seconds=30,
            path_to_python_interpreter=Path.cwd() / ".venv" / "bin" / "python",
            path_to_srt_settings=Path.cwd() / "default_srt_settings.json",
        )

    @field_validator("path_to_srt_settings", mode="after")
    @classmethod
    def _check_exists(cls, path: Path) -> Path:
        if not path.exists():
            raise ValidationError(f"{path} does not exist")
        return path
