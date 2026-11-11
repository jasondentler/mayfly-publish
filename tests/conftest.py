"""Isolated launch environment: tests never read the repository's real .env."""

import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def isolated_mcp_launcher(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repository = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    launcher = scripts / "run-mcp.sh"
    shutil.copy2(repository / "scripts/run-mcp.sh", launcher)
    (tmp_path / ".venv").symlink_to(repository / ".venv", target_is_directory=True)
    files = tmp_path / "files"
    files.mkdir()
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"FILE_ROOT={files}\n"
        "S3_ENDPOINT=https://storage.example.invalid\n"
        "S3_REGION=us-east-1\n"
        "S3_BUCKET=test-bucket\n"
        "S3_ACCESS_KEY_ID=test-access\n"
        "S3_SECRET_ACCESS_KEY=test-secret\n"
        "S3_PREFIX=mayfly-staging/\n"
        "S3_ADDRESSING_STYLE=path\n"
    )
    dotenv.chmod(0o600)
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("S3_")
        and name
        not in {
            "FILE_ROOT",
            "CONTROL_PLANE_API_KEY",
            "SIGNED_URL_TTL_SECONDS",
            "MAX_FILE_BYTES",
            "STAGED_OBJECT_MAX_AGE_HOURS",
        }
    }
    return launcher, files, environment
