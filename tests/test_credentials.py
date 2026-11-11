from pathlib import Path

import pytest

from mayfly_publish import credentials


def test_keyring_set_uses_configured_service_names_without_printing_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "S3_ACCESS_KEY_ID_KEYRING_SERVICE=mayfly-test-access\nS3_SECRET_ACCESS_KEY_KEYRING_SERVICE=mayfly-test-secret\n"
    )
    env.chmod(0o600)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("S3_ACCESS_KEY_ID_KEYRING_SERVICE", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY_KEYRING_SERVICE", raising=False)
    saved: list[tuple[str, str, str]] = []

    class Backend:
        def set_password(self, service: str, username: str, value: str) -> None:
            saved.append((service, username, value))

    values = iter(("test-access", "test-secret"))
    monkeypatch.setattr(credentials.getpass, "getpass", lambda prompt: next(values))
    monkeypatch.setattr(credentials.keyring, "get_keyring", Backend)
    monkeypatch.setattr(credentials.keyring.core, "recommended", lambda backend: True)
    assert credentials.main() == 0
    assert saved == [
        ("mayfly-test-access", "mayfly-publish", "test-access"),
        ("mayfly-test-secret", "mayfly-publish", "test-secret"),
    ]
    output = capsys.readouterr()
    assert "test-access" not in output.out + output.err
    assert "test-secret" not in output.out + output.err
