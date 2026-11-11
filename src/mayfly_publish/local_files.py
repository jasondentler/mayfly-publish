"""Open an arbitrary caller-identified file without reading its content metadata."""

import mimetypes
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .errors import PublishError

CONTENT_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")


@dataclass(frozen=True)
class OpenedFile:
    stream: BinaryIO
    size_bytes: int
    content_type: str
    device: int
    inode: int
    mtime_ns: int

    def ensure_unchanged(self) -> None:
        current = os.fstat(self.stream.fileno())
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            self.device,
            self.inode,
            self.size_bytes,
            self.mtime_ns,
        ):
            raise PublishError("file_changed", "File changed during transfer")


def open_file(root: Path, relative_path: str, max_bytes: int, content_type: str | None = None) -> OpenedFile:
    if not isinstance(relative_path, str) or not 1 <= len(relative_path) <= 1024:
        raise PublishError("invalid_input", "A relative file path is required")
    if "\\" in relative_path or "\x00" in relative_path:
        raise PublishError("invalid_input", "Invalid file path")
    path = PurePosixPath(relative_path)
    parts = relative_path.split("/")
    if path.is_absolute() or any(not part or part in {".", ".."} or part.startswith(".") for part in parts):
        raise PublishError("invalid_input", "File path must stay inside FILE_ROOT")
    if content_type is not None and not CONTENT_TYPE.fullmatch(content_type):
        raise PublishError("invalid_input", "content_type must be a valid MIME type")
    mime = (content_type or mimetypes.guess_type(relative_path, strict=False)[0] or "application/octet-stream").lower()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(root, flags | os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                child_fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child_fd
            file_fd = os.open(parts[-1], flags, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise PublishError("file_unavailable", "File is unavailable") from exc
    file_stat = os.fstat(file_fd)
    if not stat.S_ISREG(file_stat.st_mode):
        os.close(file_fd)
        raise PublishError("invalid_file", "Source must be a regular file")
    if file_stat.st_size > max_bytes:
        os.close(file_fd)
        raise PublishError("file_too_large", "File exceeds configured upload limit")
    stream = os.fdopen(file_fd, "rb")
    opened = OpenedFile(stream, file_stat.st_size, mime, file_stat.st_dev, file_stat.st_ino, file_stat.st_mtime_ns)
    try:
        opened.ensure_unchanged()
    except Exception:
        stream.close()
        raise
    return opened
