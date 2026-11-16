import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mayfly_publish.errors import PublishError
from mayfly_publish.metadata import read_local_metadata


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("exiftool"), reason="media tools unavailable")
def test_jpeg_and_mp4_metadata(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    exiftool = shutil.which("exiftool")
    assert ffmpeg is not None and exiftool is not None
    jpeg = tmp_path / "photo.JPEG"
    mp4 = tmp_path / "clip.MP4"
    subprocess.run(  # noqa: S603 - fixed test fixture command
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x32:d=1",
            "-frames:v",
            "1",
            "-y",
            str(jpeg),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - fixed test fixture command
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=32x32:d=1:r=2",
            "-c:v",
            "mpeg4",
            "-y",
            str(mp4),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - fixed test fixture command
        [exiftool, "-overwrite_original", "-Artist=Test Artist", str(jpeg)], check=True, capture_output=True
    )
    settings = SimpleNamespace(file_root=tmp_path, max_file_bytes=1_000_000)
    photo_tags = read_local_metadata(settings, "photo.JPEG")["metadata"]
    assert photo_tags["IFD0:Artist"] == "Test Artist"
    assert photo_tags["File:FileType"] == "JPEG"
    assert "SourceFile" not in photo_tags
    assert "System:Directory" not in photo_tags
    assert str(tmp_path) not in str(photo_tags)

    video_tags = read_local_metadata(settings, "clip.MP4")["metadata"]
    assert video_tags["File:FileType"] == "MP4"
    assert any("Duration" in key for key in video_tags)


def test_metadata_rejects_other_types_and_traversal(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("note")
    settings = SimpleNamespace(file_root=tmp_path, max_file_bytes=1000)
    for path in ("note.txt", "../photo.jpg"):
        with pytest.raises(PublishError) as error:
            read_local_metadata(settings, path)
        assert error.value.code == "invalid_input"
