"""Public Make targets keep setup and serving discoverable."""

import shutil
import subprocess
from pathlib import Path


def test_serve_starts_bounded_tunnel_and_setup_runs_wizard() -> None:
    project = Path(__file__).resolve().parents[1]
    make = shutil.which("make")
    assert make is not None
    serve = subprocess.run(  # noqa: S603 - make dry run does not execute the recipe
        [make, "-n", "serve", "LIFETIME_SECONDS=7200"],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "mayfly_publish.tunnel run --lifetime-seconds 7200" in serve

    setup = subprocess.run(  # noqa: S603 - make dry run does not execute the recipe
        [make, "-n", "setup"],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "uv python install 3.15" in setup
    assert "uv sync --locked --extra dev --python 3.15" in setup
    assert "mayfly_publish.setup" in setup
