import hashlib
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import pytest

from mayfly_publish.cleanup import cleanup
from mayfly_publish.errors import PublishError
from mayfly_publish.settings import Settings
from mayfly_publish.staging import Publisher


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, datetime]] = {}
        self.fail_upload = False

    def upload(self, key: str, stream: BinaryIO, content_type: str) -> None:
        if self.fail_upload:
            self.objects[key] = (b"partial", content_type, datetime.now(UTC))
            raise PublishError("storage_unavailable", "Remote upload failed")
        self.objects[key] = (stream.read(), content_type, datetime.now(UTC))

    def head(self, key: str) -> dict[str, object] | None:
        if key not in self.objects:
            return None
        data, content_type, _ = self.objects[key]
        return {"ContentLength": len(data), "ContentType": content_type}

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def sign_get(self, key: str, ttl: int) -> str:
        return f"https://example.invalid/{key}?signed={ttl}"

    def list_staged(self) -> list[tuple[str, datetime]]:
        return [(key, value[2]) for key, value in self.objects.items()]


def settings(root: Path) -> Settings:
    return Settings(
        root,
        "https://example.invalid",
        "us-east-1",
        "test-bucket",
        "fake",
        "fake",
        "mayfly-staging/",
        "path",
        7200,
        100_000_000,
        25,
        "INFO",
    )


def test_publish_revoke_and_no_source_details(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "confidential.project"
    path.write_bytes(b"arbitrary bytes \x00\xff")
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    storage = FakeStorage()
    publisher = Publisher(settings(tmp_path), storage)  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO, logger="mayfly_publish"):
        result = publisher.temp_publish("confidential.project", content_type="application/x-project")
    assert set(result) == {"staging_id", "url", "url_expires_at", "content_type", "size_bytes", "status"}
    assert result["content_type"] == "application/x-project"
    assert "confidential" not in str(result)
    assert "confidential" not in caplog.text
    assert str(result["url"]) not in caplog.text
    assert len(storage.objects) == 1
    assert publisher.revoke_object(str(result["staging_id"]))["status"] == "revoked"
    assert publisher.revoke_object(str(result["staging_id"]))["status"] == "revoked"
    assert not storage.objects
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


def test_failed_upload_never_returns_url(tmp_path: Path) -> None:
    (tmp_path / "payload").write_bytes(b"data")
    storage = FakeStorage()
    storage.fail_upload = True
    publisher = Publisher(settings(tmp_path), storage)  # type: ignore[arg-type]
    with pytest.raises(PublishError):
        publisher.temp_publish("payload")
    assert not storage.objects


def test_revoke_rejects_unmanaged_key(tmp_path: Path) -> None:
    publisher = Publisher(settings(tmp_path), FakeStorage())  # type: ignore[arg-type]
    with pytest.raises(PublishError) as error:
        publisher.revoke_object("backup/private")
    assert error.value.code == "invalid_input"


def test_stateless_cleanup_respects_url_lifetime(tmp_path: Path) -> None:
    storage = FakeStorage()
    key = f"mayfly-staging/{uuid.uuid4()}"
    storage.objects[key] = (b"old", "application/octet-stream", datetime.now(UTC) - timedelta(hours=26))
    new_key = f"mayfly-staging/{uuid.uuid4()}"
    storage.objects[new_key] = (b"new", "application/octet-stream", datetime.now(UTC) - timedelta(hours=24))
    config = replace(settings(tmp_path), max_age_hours=25)
    assert cleanup(config, storage, dry_run=True)["eligible"] == 1  # type: ignore[arg-type]
    assert len(storage.objects) == 2
    assert cleanup(config, storage)["deleted"] == 1  # type: ignore[arg-type]
    assert set(storage.objects) == {new_key}
