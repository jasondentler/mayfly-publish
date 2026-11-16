from pathlib import Path

import pytest

from mayfly_publish.errors import PublishError
from mayfly_publish.local_files import list_files, open_file


def test_list_files_includes_nested_paths_and_skips_unuploadable_entries(tmp_path: Path) -> None:
    (tmp_path / "top.jpg").write_bytes(b"photo")
    (tmp_path / "upper.JPEG").write_bytes(b"photo")
    (tmp_path / "clip.MP4").write_bytes(b"video")
    (tmp_path / "note.txt").write_text("note")
    (tmp_path / "extensionless").write_bytes(b"")
    (tmp_path / "too-large.jpg").write_bytes(b"oversized")
    nested = tmp_path / "trip" / "day1"
    nested.mkdir(parents=True)
    (nested / "image.jpg").write_bytes(b"image")
    (nested / "ignored.png").write_bytes(b"image")
    (nested / ".hidden.jpg").write_bytes(b"hidden")
    (tmp_path / ".private").mkdir()
    (tmp_path / ".private" / "secret.jpg").write_bytes(b"secret")
    (tmp_path / "linked.jpg").symlink_to(tmp_path / "top.jpg")
    (tmp_path / "linked-folder").symlink_to(nested, target_is_directory=True)
    (tmp_path / "bad\\name.jpg").write_bytes(b"bad")

    assert list_files(tmp_path, 5) == {
        "files": ["clip.MP4", "top.jpg", "trip/day1/image.jpg", "upper.JPEG"],
        "folders": ["trip", "trip/day1"],
    }


def test_arbitrary_types_extensionless_and_empty(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello")
    (tmp_path / "custom.noveltype").write_bytes(b"\x00\xff\x10")
    (tmp_path / "extensionless").write_bytes(b"")
    for name, expected in (
        ("note.txt", "text/plain"),
        ("custom.noveltype", "application/octet-stream"),
        ("extensionless", "application/octet-stream"),
    ):
        opened = open_file(tmp_path, name, 10000)
        with opened.stream:
            assert opened.content_type == expected
            assert opened.stream.read() == (tmp_path / name).read_bytes()
            opened.ensure_unchanged()
    empty = open_file(tmp_path, "extensionless", 10000)
    with empty.stream:
        assert empty.size_bytes == 0


@pytest.mark.parametrize(
    "relative", ["../secret", "/outside/file", ".hidden", "folder/../file", "folder//file", "folder\\file"]
)
def test_paths_outside_scope_rejected(tmp_path: Path, relative: str) -> None:
    with pytest.raises(PublishError) as error:
        open_file(tmp_path, relative, 10000)
    assert error.value.code == "invalid_input"


def test_symlinks_and_nested_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / "nested"
    directory.mkdir()
    (directory / "data").write_bytes(b"payload")
    (tmp_path / "link").symlink_to(directory / "data")
    (tmp_path / "linkdir").symlink_to(directory, target_is_directory=True)
    for relative in ("link", "linkdir/data"):
        with pytest.raises(PublishError):
            open_file(tmp_path, relative, 10000)
    opened = open_file(tmp_path, "nested/data", 10000, "application/x-custom")
    with opened.stream:
        assert opened.content_type == "application/x-custom"
    with pytest.raises(PublishError) as invalid:
        open_file(tmp_path, "nested/data", 10000, "text/plain\r\nInjected: yes")
    assert invalid.value.code == "invalid_input"


def test_size_and_changed_file(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_bytes(b"original")
    with pytest.raises(PublishError) as error:
        open_file(tmp_path, "data", 1)
    assert error.value.code == "file_too_large"
    opened = open_file(tmp_path, "data", 10000)
    with opened.stream:
        with path.open("ab") as handle:
            handle.write(b"change")
        with pytest.raises(PublishError) as changed:
            opened.ensure_unchanged()
        assert changed.value.code == "file_changed"
