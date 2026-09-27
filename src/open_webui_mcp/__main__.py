from __future__ import annotations

import argparse
import logging

from .config import get_settings
from .http_server import run_http
from .server import create_mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Open WebUI knowledge search MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")

    if args.transport == "http":
        run_http(settings)
    else:
        create_mcp(settings).run(transport="stdio")


if __name__ == "__main__":
    main()
