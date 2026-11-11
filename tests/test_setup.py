"""Guided setup tests use synthetic settings and an in-memory keyring."""

import subprocess
from pathlib import Path

import pytest

from mayfly_publish import setup
from mayfly_publish.settings import _dotenv


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, value: str) -> None:
        self.values[(service, username)] = value


def test_setup_gathers_settings_and_secrets_without_cloud_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run-mcp.sh").write_text("#!/bin/sh\n")
    file_root = tmp_path / "files"
    answers = iter(
        (
            str(file_root),
            "https://storage.example.invalid/api/s3",
            "test-region",
            "test-bucket",
            "path",
            "yes",
            "tunnel_abcdef",
        )
    )
    monkeypatch.setattr(setup, "_ask", lambda label, default="": next(answers))
    secrets = iter(("fake-access", "fake-secret", "fake-tunnel-key"))
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: next(secrets))
    backend = FakeKeyring()
    monkeypatch.setattr(setup.keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(setup.keyring.core, "recommended", lambda value: True)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/fake/bin/tunnel-client")
    monkeypatch.setattr(setup.Settings, "load", lambda env_file: object())
    commands: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda command, check: commands.append(command))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert setup.main() == 0
    data = _dotenv(tmp_path / ".env")
    assert "S3_ENDPOINT" not in data
    assert "S3_BUCKET" not in data
    assert data["S3_ENDPOINT_KEYRING_SERVICE"] == setup.ENDPOINT_SERVICE
    assert data["S3_BUCKET_KEYRING_SERVICE"] == setup.BUCKET_SERVICE
    assert "S3_ACCESS_KEY_ID" not in data
    assert "S3_SECRET_ACCESS_KEY" not in data
    assert len(backend.values) == 5
    assert commands[0][-2:] == ["--mcp-command", str(tmp_path / "scripts" / "run-mcp.sh")]
    output = capsys.readouterr().out
    assert "Next: make serve" in output
    assert all(secret not in output for secret in backend.values.values())


def test_setup_preserves_existing_configuration_and_keyring_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    files = tmp_path / "files"
    files.mkdir()
    env = tmp_path / ".env"
    env.write_text(
        f"FILE_ROOT={files}\nS3_ENDPOINT_KEYRING_SERVICE={setup.ENDPOINT_SERVICE}\n"
        f"S3_REGION=test-region\nS3_BUCKET_KEYRING_SERVICE={setup.BUCKET_SERVICE}\nS3_ADDRESSING_STYLE=path\n"
        f"S3_ACCESS_KEY_ID_KEYRING_SERVICE={setup.ACCESS_SERVICE}\n"
        f"S3_SECRET_ACCESS_KEY_KEYRING_SERVICE={setup.SECRET_SERVICE}\n"
    )
    env.chmod(0o600)
    original = env.read_bytes()
    backend = FakeKeyring()
    for service in (
        setup.ACCESS_SERVICE,
        setup.SECRET_SERVICE,
        setup.TUNNEL_KEYRING_SERVICE,
        setup.ENDPOINT_SERVICE,
        setup.BUCKET_SERVICE,
    ):
        backend.set_password(service, "mayfly-publish", "existing-secret")
    monkeypatch.setattr(setup.keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(setup.keyring.core, "recommended", lambda value: True)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/fake/bin/tunnel-client")
    monkeypatch.setattr(setup.Settings, "load", lambda env_file: object())
    monkeypatch.setattr(setup, "_ask", lambda label, default="": pytest.fail("should not prompt"))
    profile = tmp_path / "config" / "tunnel-client" / "mayfly-publish.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("existing profile")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert setup.main() == 0
    assert env.read_bytes() == original
    assert profile.read_text() == "existing profile"
