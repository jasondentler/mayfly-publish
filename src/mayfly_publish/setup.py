"""Interactive local installation without storing secrets in project files."""

import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import keyring
from keyring.backend import KeyringBackend

from .errors import PublishError
from .settings import KEYRING_USERNAME, Settings, _dotenv
from .tunnel import TUNNEL_KEYRING_SERVICE, TUNNEL_PROFILE

ACCESS_SERVICE = "mayfly-publish-access-key"
SECRET_SERVICE = "mayfly-publish-secret-key"  # noqa: S105 - keyring service name, not a credential
ENDPOINT_SERVICE = "mayfly-publish-endpoint"
BUCKET_SERVICE = "mayfly-publish-bucket"


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _secret(backend: KeyringBackend, service: str, label: str) -> None:
    stored = backend.get_password(service, KEYRING_USERNAME)
    if stored:
        print(f"{label}: already in the system keyring")
        return
    value = getpass.getpass(f"{label}: ")
    if not value:
        raise PublishError("configuration", f"{label} is required")
    backend.set_password(service, KEYRING_USERNAME, value)
    print(f"{label}: stored in the system keyring")


def _write_env(env_file: Path, values: dict[str, str]) -> None:
    temporary = env_file.with_name(".env.setup-tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            for name, value in values.items():
                if "\n" in value or "\r" in value:
                    raise PublishError("configuration", f"Invalid {name}")
                output.write(f"{name}={value}\n")
        temporary.replace(env_file)
    finally:
        temporary.unlink(missing_ok=True)


def _protect_storage_config(project: Path, backend: KeyringBackend) -> None:
    """Move account-specific storage settings out of the project directory."""
    env_file = project / ".env"
    values = _dotenv(env_file)
    changed = False
    for name, service in (("S3_ENDPOINT", ENDPOINT_SERVICE), ("S3_BUCKET", BUCKET_SERVICE)):
        value = values.pop(name, None)
        if value:
            backend.set_password(service, KEYRING_USERNAME, value)
            values[f"{name}_KEYRING_SERVICE"] = service
            changed = True
    if changed:
        _write_env(env_file, values)
        print("Storage endpoint and bucket moved to the system keyring")


def _configure_storage(project: Path) -> None:
    env_file = project / ".env"
    existing = _dotenv(env_file)
    required = {
        "FILE_ROOT": ("Local file directory", "~/ToPublish"),
        "S3_ENDPOINT": ("S3-compatible HTTPS endpoint", ""),
        "S3_REGION": ("S3 signing region", "us-east-1"),
        "S3_BUCKET": ("Existing private bucket", ""),
        "S3_ADDRESSING_STYLE": ("Addressing style (path, virtual, auto)", "path"),
    }
    if (
        all(
            (existing.get(name) or existing.get(f"{name}_KEYRING_SERVICE"))
            and "<" not in existing.get(name, "")
            and existing.get(name) != "replace-locally"
            for name in required
        )
        and existing.get("S3_ACCESS_KEY_ID_KEYRING_SERVICE")
        and existing.get("S3_SECRET_ACCESS_KEY_KEYRING_SERVICE")
        and Path(existing["FILE_ROOT"]).expanduser().is_dir()
        and ("S3_ENDPOINT_KEYRING_SERVICE" in existing or urlparse(existing["S3_ENDPOINT"]).scheme == "https")
    ):
        print("Storage configuration: existing .env retained")
        return
    values = dict(existing)
    for name, (label, fallback) in required.items():
        values[name] = _ask(label, existing.get(name, fallback))
        if not values[name]:
            raise PublishError("configuration", f"{name} is required")
    endpoint = urlparse(values["S3_ENDPOINT"])
    if endpoint.scheme != "https" or not endpoint.hostname:
        raise PublishError("configuration", "S3_ENDPOINT must be a valid HTTPS URL")
    if values["S3_ADDRESSING_STYLE"] not in {"path", "virtual", "auto"}:
        raise PublishError("configuration", "S3_ADDRESSING_STYLE must be path, virtual, or auto")
    root = Path(values["FILE_ROOT"]).expanduser()
    if not root.is_dir():
        if _ask(f"Create local directory {root}? (yes/no)", "yes").lower() != "yes":
            raise PublishError("configuration", "FILE_ROOT must exist")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    values.pop("S3_ACCESS_KEY_ID", None)
    values.pop("S3_SECRET_ACCESS_KEY", None)
    values["S3_ACCESS_KEY_ID_KEYRING_SERVICE"] = existing.get("S3_ACCESS_KEY_ID_KEYRING_SERVICE", ACCESS_SERVICE)
    values["S3_SECRET_ACCESS_KEY_KEYRING_SERVICE"] = existing.get(
        "S3_SECRET_ACCESS_KEY_KEYRING_SERVICE", SECRET_SERVICE
    )
    defaults = {
        "S3_PREFIX": "mayfly-staging/",
        "SIGNED_URL_TTL_SECONDS": "7200",
        "MAX_FILE_BYTES": "104857600",
        "STAGED_OBJECT_MAX_AGE_HOURS": "25",
        "LOG_LEVEL": "INFO",
    }
    for name, value in defaults.items():
        values.setdefault(name, value)
    _write_env(env_file, values)
    print("Storage configuration: .env saved with mode 0600")


def _configure_tunnel(project: Path) -> None:
    profile_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "tunnel-client"
    profile = profile_dir / f"{TUNNEL_PROFILE}.yaml"
    if profile.is_file():
        print("Tunnel profile: existing profile retained")
        return
    tunnel_id = _ask("Existing tunnel ID")
    if not re.fullmatch(r"tunnel_[a-zA-Z0-9]+", tunnel_id):
        raise PublishError("configuration", "A valid existing tunnel ID is required")
    executable = shutil.which("tunnel-client")
    if not executable:
        raise PublishError("configuration", "Install tunnel-client before running make setup")
    subprocess.run(  # noqa: S603 - fixed executable; arguments are passed without a shell
        [
            executable,
            "init",
            "--sample",
            "sample_mcp_stdio_local",
            "--profile",
            TUNNEL_PROFILE,
            "--tunnel-id",
            tunnel_id,
            "--mcp-command",
            str(project / "scripts" / "run-mcp.sh"),
        ],
        check=True,
    )
    print("Tunnel profile: initialized")


def main() -> int:
    try:
        if not shutil.which("tunnel-client"):
            raise PublishError("configuration", "Install tunnel-client before running make setup")
        backend = keyring.get_keyring()
        if not keyring.core.recommended(backend):
            raise PublishError("configuration", "No usable system keyring backend is available")
        project = Path.cwd()
        _configure_storage(project)
        _protect_storage_config(project, backend)
        data = _dotenv(project / ".env")
        _secret(backend, data["S3_ACCESS_KEY_ID_KEYRING_SERVICE"], "S3 access key ID")
        _secret(backend, data["S3_SECRET_ACCESS_KEY_KEYRING_SERVICE"], "S3 secret access key")
        _secret(backend, TUNNEL_KEYRING_SERVICE, "Tunnel runtime API key")
        _configure_tunnel(project)
        Settings.load(project / ".env")
        print("Setup complete. Next: make serve")
        return 0
    except EOFError, KeyboardInterrupt:
        print("setup_incomplete: input was interrupted", file=sys.stderr)
    except PublishError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
    except OSError, subprocess.CalledProcessError, keyring.errors.KeyringError:
        print("setup_incomplete: could not configure the system keyring or tunnel", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
