"""Read ExifTool metadata from a securely opened local media file."""

import json
import shutil
import subprocess
from pathlib import PurePosixPath
from typing import Any

from .errors import PublishError
from .local_files import LISTED_EXTENSIONS, open_file
from .settings import Settings

MAX_METADATA_BYTES = 10_000_000
METADATA_TIMEOUT_SECONDS = 30
PATH_FIELDS = {"SourceFile", "System:FileName", "System:Directory", "System:FilePath"}


def read_local_metadata(settings: Settings, relative_path: str) -> dict[str, object]:
    """Return all ExifTool-readable tags without exposing the source location."""
    if not isinstance(relative_path, str) or PurePosixPath(relative_path).suffix.lower() not in LISTED_EXTENSIONS:
        raise PublishError("invalid_input", "Metadata supports JPEG and MP4 files only")
    if not shutil.which("exiftool"):
        raise PublishError("metadata_unavailable", "ExifTool is required for metadata")
    opened = open_file(settings.file_root, relative_path, settings.max_file_bytes)
    with opened.stream:
        fd = opened.stream.fileno()
        command = ["exiftool", "-json", "-G1:4", "-a", "-s", "-ee", "-U", "-n", "-struct", f"/dev/fd/{fd}"]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed ExifTool command; only a validated file descriptor varies
                command,
                capture_output=True,
                check=False,
                pass_fds=(fd,),
                timeout=METADATA_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PublishError("metadata_unavailable", "Could not read local metadata") from exc
        if completed.returncode or len(completed.stdout) > MAX_METADATA_BYTES:
            raise PublishError("metadata_unavailable", "Could not read local metadata")
        try:
            parsed: Any = json.loads(completed.stdout)
        except (UnicodeDecodeError, ValueError) as exc:
            raise PublishError("metadata_unavailable", "Could not read local metadata") from exc
        if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
            raise PublishError("metadata_unavailable", "Could not read local metadata")
        opened.ensure_unchanged()
        tags = {key: value for key, value in parsed[0].items() if key not in PATH_FIELDS}
        return {"metadata": tags}
