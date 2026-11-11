"""Bound the lifetime of local MCP and tunnel processes."""

import argparse
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence

DEFAULT_LIFETIME_SECONDS = 3600
MAX_LIFETIME_SECONDS = 86400


def lifetime_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lifetime must be an integer number of seconds") from exc
    if not 1 <= seconds <= MAX_LIFETIME_SECONDS:
        raise argparse.ArgumentTypeError("lifetime must be between 1 and 86400 seconds")
    return seconds


def _stop_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_limited(command: Sequence[str], environment: Mapping[str, str], seconds: int) -> int:
    """Run a process group until it exits or its mandatory lifetime expires."""
    process = subprocess.Popen(list(command), env=dict(environment), start_new_session=True)  # noqa: S603
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        print(f"runtime_limit_reached: process stopped after {seconds} seconds", file=sys.stderr)
        _stop_group(process)
        return 0
    except KeyboardInterrupt:
        _stop_group(process)
        return 130


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the stdio MCP server for a bounded time")
    parser.add_argument("--lifetime-seconds", type=lifetime_seconds, default=DEFAULT_LIFETIME_SECONDS)
    args = parser.parse_args(argv)
    return run_limited([sys.executable, "-m", "mayfly_publish"], os.environ, args.lifetime_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
