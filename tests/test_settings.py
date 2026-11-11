from pathlib import Path

import pytest

from mayfly_publish.errors import PublishError
from mayfly_publish.settings import Settings, _keyring_secret


def test_dotenv_permissions_and_keyring_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        f"FILE_ROOT={tmp_path}\nS3_ENDPOINT=https://example.invalid\nS3_BUCKET=bucket\n"
        "S3_ACCESS_KEY_ID_KEYRING_SERVICE=mayfly-access\n"
        "S3_SECRET_ACCESS_KEY_KEYRING_SERVICE=mayfly-secret\n"
    )
    env.chmod(0o644)
    with pytest.raises(PublishError):
        Settings.load(env)
    env.chmod(0o600)
    monkeypatch.setattr("mayfly_publish.settings._keyring_secret", lambda service: "fake-" + service)
    loaded = Settings.load(env)
    assert loaded.access_key == "fake-mayfly-access"
    assert loaded.secret_key.endswith("mayfly-secret")


def test_keyring_lookup_uses_service_and_fixed_username(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class Backend:
        priority = 5

        def get_password(self, service: str, username: str) -> str:
            calls.append((service, username))
            return "test-value"

    monkeypatch.setattr("mayfly_publish.settings.keyring.get_keyring", lambda: Backend())
    assert _keyring_secret("mayfly-test") == "test-value"
    assert calls == [("mayfly-test", "mayfly-publish")]


def test_keyring_fails_closed_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    class Backend:
        priority = 0

        def get_password(self, service: str, username: str) -> str:
            raise AssertionError("must not read an unavailable backend")

    monkeypatch.setattr("mayfly_publish.settings.keyring.get_keyring", lambda: Backend())
    with pytest.raises(PublishError) as error:
        _keyring_secret("mayfly-test")
    assert error.value.code == "configuration"


def test_s3_endpoint_accepts_safe_path(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        f"FILE_ROOT={tmp_path}\n"
        "S3_ENDPOINT=https://storage.example.invalid/api/s3\n"
        "S3_BUCKET=bucket\nS3_ACCESS_KEY_ID=fake-access\nS3_SECRET_ACCESS_KEY=fake-secret\n"
    )
    env.chmod(0o600)
    assert Settings.load(env).endpoint == "https://storage.example.invalid/api/s3"
    env.write_text(env.read_text().replace("/api/s3", "/api/../s3"))
    with pytest.raises(PublishError, match="safe path"):
        Settings.load(env)


def test_endpoint_and_bucket_can_be_loaded_from_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        f"FILE_ROOT={tmp_path}\nS3_ENDPOINT_KEYRING_SERVICE=mayfly-test-endpoint\n"
        "S3_BUCKET_KEYRING_SERVICE=mayfly-test-bucket\n"
        "S3_ACCESS_KEY_ID=fake-access\nS3_SECRET_ACCESS_KEY=fake-secret\n"
    )
    env.chmod(0o600)
    values = {
        "mayfly-test-endpoint": "https://storage.example.invalid/api/s3",
        "mayfly-test-bucket": "test-bucket",
    }
    monkeypatch.setattr("mayfly_publish.settings._keyring_secret", values.__getitem__)
    loaded = Settings.load(env)
    assert loaded.endpoint == values["mayfly-test-endpoint"]
    assert loaded.bucket == values["mayfly-test-bucket"]
