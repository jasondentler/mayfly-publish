import asyncio
import base64
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import ImageContent

from mayfly_publish.errors import PublishError
from mayfly_publish.preview import preview_local_file
from mayfly_publish.server import create_server
from mayfly_publish.settings import Settings


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_local_jpeg_and_mp4_previews(tmp_path: Path) -> None:
    for name, source in (("photo.JPEG", "color=c=red:s=128x96:d=1"), ("clip.MP4", "testsrc=s=128x96:d=2:r=2")):
        command = ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", source]
        if name.lower().endswith(".mp4"):
            command.extend(("-c:v", "mpeg4"))
        command.extend(("-frames:v", "1" if name.lower().endswith(".jpeg") else "4", "-y", str(tmp_path / name)))
        subprocess.run(command, check=True, capture_output=True)  # noqa: S603 - fixed test fixture command

    settings = SimpleNamespace(file_root=tmp_path, max_file_bytes=10_000_000)
    photo = preview_local_file(settings, "photo.JPEG")
    assert len(photo) == 1
    assert isinstance(photo[0], ImageContent)
    assert base64.b64decode(photo[0].data).startswith(b"\xff\xd8")

    video = preview_local_file(settings, "clip.MP4")
    frames = [part for part in video if isinstance(part, ImageContent)]
    assert len(frames) >= 2
    assert all(base64.b64decode(frame.data).startswith(b"\xff\xd8") for frame in frames)

    config = Settings(
        tmp_path,
        "https://example.invalid",
        "us-east-1",
        "bucket",
        "fake",
        "fake",
        "mayfly-staging/",
        "path",
        7200,
        10_000_000,
        25,
        "INFO",
    )
    server = create_server(config)
    content = asyncio.run(server.call_tool("preview_local_file", {"relative_path": "photo.JPEG"}))
    assert len(content) == 1
    assert isinstance(content[0], ImageContent)


def test_preview_rejects_other_file_types(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("note")
    settings = SimpleNamespace(file_root=tmp_path, max_file_bytes=1000)
    with pytest.raises(PublishError) as error:
        preview_local_file(settings, "note.txt")
    assert error.value.code == "invalid_input"
