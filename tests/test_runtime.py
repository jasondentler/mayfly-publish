import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mayfly_publish.runtime import lifetime_seconds, run_limited


@pytest.mark.parametrize("value", ["0", "86401", "never", "1.5", "-1"])
def test_lifetime_cannot_be_disabled_or_exceed_one_day(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        lifetime_seconds(value)
    assert lifetime_seconds("3600") == 3600
    assert lifetime_seconds("86400") == 86400


def test_process_stops_when_lifetime_expires() -> None:
    started = time.monotonic()
    result = run_limited([sys.executable, "-c", "import time; time.sleep(30)"], os.environ, 1)
    assert result == 0
    assert time.monotonic() - started < 4


def test_stdio_mcp_launcher_exits_at_deadline(isolated_mcp_launcher: tuple[Path, Path, dict[str, str]]) -> None:
    launcher, _, environment = isolated_mcp_launcher
    process = subprocess.Popen(  # noqa: S603
        [str(launcher), "--lifetime-seconds", "1"],
        cwd=launcher.parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.wait(timeout=4) == 0
        assert process.stdout is not None
        assert process.stdout.read() == b""
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
