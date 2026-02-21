import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator


class CodeSandboxSettings(BaseModel):
    code_timeout_seconds: int
    user: str | None
    path_to_srt_settings: Path
    working_directory: Path
    path_to_python_interpreter: Path = Path("python")


class FullSettings(CodeSandboxSettings):
    transport: str
    stateless: bool
    port: int
    host: str
    path: str
    log_level: int
    installed_python_dependencies: list[str] = Field(default_factory=list)

    @classmethod
    def using_defaults(cls) -> "FullSettings":
        return cls(
            transport="http",
            stateless=True,
            port=6400,
            host="localhost",
            path="/mcp",
            log_level=logging.INFO,
            code_timeout_seconds=30,
            path_to_python_interpreter=Path.cwd() / ".venv" / "bin" / "python",
            working_directory=Path.cwd() / ".testing",
            path_to_srt_settings=Path.cwd() / "default_srt_settings.json",
            user=None,
        )

    @field_validator("path_to_srt_settings", mode="after")
    @classmethod
    def _check_exists(cls, path: Path) -> Path:
        if not path.exists():
            raise ValidationError(f"{path} does not exist")
        return path
