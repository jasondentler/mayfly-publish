"""CLI entrypoint for stdio MCP and separate cleanup worker."""

import argparse
import json
import logging
import sys

from .cleanup import cleanup
from .errors import PublishError
from .server import create_server
from .settings import Settings
from .storage import Storage


def main() -> None:
    parser = argparse.ArgumentParser(prog="mayfly-publish")
    sub = parser.add_subparsers(dest="command")
    cleanup_parser = sub.add_parser("cleanup", help="Delete old tracked staging objects")
    cleanup_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings.load()
        app_logger = logging.getLogger("mayfly_publish")
        app_logger.setLevel(settings.log_level)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        app_logger.addHandler(handler)
        if args.command == "cleanup":
            result = cleanup(settings, Storage(settings), args.dry_run)
            print(json.dumps(result))
            if result["failed"]:
                raise SystemExit(1)
        else:
            create_server(settings).run(transport="stdio")
    except PublishError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
