"""Return bounded local media previews as MCP image content."""

import base64
import math
import shutil
import subprocess
from pathlib import PurePosixPath

from mcp.types import ImageContent, TextContent

from .errors import PublishError
from .local_files import LISTED_EXTENSIONS, open_file
from .settings import Settings

MAX_PREVIEW_BYTES = 2_000_000
PREVIEW_TIMEOUT_SECONDS = 15


def _run(command: list[str], fd: int) -> bytes:
    try:
        completed = subprocess.run(  # noqa: S603 - command and arguments are constructed locally
            command,
            capture_output=True,
            check=False,
            pass_fds=(fd,),
            timeout=PREVIEW_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError("preview_unavailable", "Could not create local preview") from exc
    if completed.returncode or not completed.stdout or len(completed.stdout) > MAX_PREVIEW_BYTES:
        raise PublishError("preview_unavailable", "Could not create local preview")
    return completed.stdout


def _frame(fd: int, seconds: float) -> ImageContent:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-ss",
        str(seconds),
        "-i",
        f"/dev/fd/{fd}",
        "-frames:v",
        "1",
        "-vf",
        "scale=960:960:force_original_aspect_ratio=decrease",
        "-q:v",
        "5",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    return ImageContent(type="image", data=base64.b64encode(_run(command, fd)).decode("ascii"), mimeType="image/jpeg")


def _duration(fd: int) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        f"/dev/fd/{fd}",
    ]
    try:
        value = float(_run(command, fd).decode("ascii").strip())
    except PublishError, UnicodeDecodeError, ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def preview_local_file(settings: Settings, relative_path: str) -> list[TextContent | ImageContent]:
    """Create a local JPEG preview or sample up to three MP4 frames."""
    if not isinstance(relative_path, str) or PurePosixPath(relative_path).suffix.lower() not in LISTED_EXTENSIONS:
        raise PublishError("invalid_input", "Preview supports JPEG and MP4 files only")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise PublishError("preview_unavailable", "ffmpeg and ffprobe are required for previews")
    opened = open_file(settings.file_root, relative_path, settings.max_file_bytes)
    with opened.stream:
        fd = opened.stream.fileno()
        suffix = PurePosixPath(relative_path).suffix.lower()
        if suffix != ".mp4":
            frame = _frame(fd, 0)
            opened.ensure_unchanged()
            return [frame]
        duration = _duration(fd)
        moments = [0.0] if duration is None else sorted({0.0, round(duration * 0.5, 2), round(duration * 0.9, 2)})
        result: list[TextContent | ImageContent] = []
        for moment in moments:
            opened.stream.seek(0)
            try:
                frame = _frame(fd, moment)
            except PublishError:
                if not result:
                    raise
                continue
            result.extend((TextContent(type="text", text=f"Frame at {moment:.2f}s"), frame))
        opened.ensure_unchanged()
        return result
