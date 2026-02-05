import typer

from mcp_run_isolated_python.log.logger import get_logger

logger = get_logger(__name__)


def main():
    logger.info("Hi! This package is WIP and does not have any functionality yet - just wanted to reserve pypi name :)")


if __name__ == "__main__":
    typer.run(main)
