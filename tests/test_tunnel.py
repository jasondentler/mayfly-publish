import os

import pytest

from mayfly_publish import tunnel


def test_store_runtime_key_without_printing_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    saved: list[tuple[str, str, str]] = []

    class Backend:
        def set_password(self, service: str, username: str, value: str) -> None:
            saved.append((service, username, value))

    monkeypatch.setenv("CONTROL_PLANE_API_KEY", "test-runtime-secret")
    monkeypatch.setattr(tunnel.keyring, "get_keyring", Backend)
    monkeypatch.setattr(tunnel.keyring.core, "recommended", lambda backend: True)
    assert tunnel.main(["store"]) == 0
    assert saved == [("mayfly-publish-tunnel-api-key", "mayfly-publish", "test-runtime-secret")]
    assert "test-runtime-secret" not in capsys.readouterr().out


def test_tunnel_launcher_keeps_secret_out_of_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[tuple[str, list[str], dict[str, str]]] = []

    def fake_exec(program: str, arguments: list[str], environment: dict[str, str]) -> None:
        launched.append((program, arguments, environment))
        raise SystemExit(0)

    monkeypatch.setattr(tunnel, "_keyring_secret", lambda service: "test-runtime-secret")
    monkeypatch.setattr(os, "execvpe", fake_exec)
    with pytest.raises(SystemExit):
        tunnel.main(["doctor"])
    program, arguments, environment = launched[0]
    assert program == "tunnel-client"
    assert arguments == ["tunnel-client", "doctor", "--profile", "mayfly-publish", "--explain"]
    assert environment["CONTROL_PLANE_API_KEY"] == "test-runtime-secret"
    assert all("test-runtime-secret" not in argument for argument in arguments)


def test_tunnel_run_has_bounded_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[tuple[list[str], dict[str, str], int]] = []

    def fake_run(command: list[str], environment: dict[str, str], seconds: int) -> int:
        launched.append((command, environment, seconds))
        return 0

    monkeypatch.setattr(tunnel, "_keyring_secret", lambda service: "test-runtime-secret")
    monkeypatch.setattr(tunnel, "run_limited", fake_run)
    assert tunnel.main(["run", "--lifetime-seconds", "7200"]) == 0
    command, environment, seconds = launched[0]
    assert command == ["tunnel-client", "run", "--profile", "mayfly-publish"]
    assert environment["CONTROL_PLANE_API_KEY"] == "test-runtime-secret"
    assert seconds == 7200
