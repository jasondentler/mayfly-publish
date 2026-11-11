"""Startup configuration and cross-platform system keyring secret lookup."""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

import keyring

from .errors import PublishError


def _dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PublishError("configuration", ".env must have mode 0600")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PublishError("configuration", "Invalid .env line")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


KEYRING_USERNAME = "mayfly-publish"


def _keyring_secret(service: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", service):
        raise PublishError("configuration", "Invalid keyring service name")
    try:
        backend = keyring.get_keyring()
        if not keyring.core.recommended(backend):
            raise PublishError("configuration", "No usable system keyring backend is available")
        value = backend.get_password(service, KEYRING_USERNAME)
    except PublishError:
        raise
    except Exception as exc:
        raise PublishError("configuration", "System keyring credential unavailable") from exc
    if not value:
        raise PublishError("configuration", "System keyring credential unavailable")
    return value


@dataclass(frozen=True)
class Settings:
    file_root: Path
    endpoint: str
    region: str
    bucket: str
    access_key: str
    secret_key: str
    prefix: str
    addressing_style: Literal["path", "virtual", "auto"]
    ttl: int
    max_file_bytes: int
    max_age_hours: int
    log_level: str

    @classmethod
    def load(cls, env_file: Path | None = None) -> Settings:
        data = _dotenv(env_file or Path.cwd() / ".env") | dict(os.environ)

        def required(name: str) -> str:
            value = data.get(name, "").strip()
            if not value or value == "replace-locally" or "<" in value or ">" in value:
                raise PublishError("configuration", f"{name} is required")
            return value

        def secret(name: str) -> str:
            service = data.get(f"{name}_KEYRING_SERVICE", "")
            return _keyring_secret(service) if service else required(name)

        def number(name: str, default: str) -> int:
            try:
                value = int(data.get(name, default))
            except ValueError as exc:
                raise PublishError("configuration", f"{name} must be an integer") from exc
            if value <= 0:
                raise PublishError("configuration", f"{name} must be positive")
            return value

        root = Path(data.get("FILE_ROOT", "~/ToPublish")).expanduser()
        if not root.is_dir() or root.is_symlink() or not os.access(root, os.R_OK):
            raise PublishError("configuration", "FILE_ROOT must be a readable directory")
        endpoint = secret("S3_ENDPOINT")
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or (
                parsed.path not in ("", "/")
                and not re.fullmatch(r"/[a-zA-Z0-9._~-]+(?:/[a-zA-Z0-9._~-]+)*", parsed.path)
            )
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or parsed.query
            or parsed.fragment
        ):
            raise PublishError("configuration", "S3_ENDPOINT must be an HTTPS endpoint with a safe path")
        prefix = data.get("S3_PREFIX", "mayfly-staging/")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*/", prefix):
            raise PublishError("configuration", "S3_PREFIX must be a simple directory prefix")
        addressing_style = data.get("S3_ADDRESSING_STYLE", "path")
        if addressing_style not in {"path", "virtual", "auto"}:
            raise PublishError("configuration", "S3_ADDRESSING_STYLE must be path, virtual, or auto")
        ttl = number("SIGNED_URL_TTL_SECONDS", "7200")
        if not 300 <= ttl <= 86400:
            raise PublishError("configuration", "SIGNED_URL_TTL_SECONDS must be 300–86400")
        log_level = data.get("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise PublishError("configuration", "LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR")
        max_age = number("STAGED_OBJECT_MAX_AGE_HOURS", "25")
        if max_age < 25:
            raise PublishError("configuration", "STAGED_OBJECT_MAX_AGE_HOURS must be at least 25")
        return cls(
            root,
            endpoint.rstrip("/"),
            data.get("S3_REGION", "us-east-1"),
            secret("S3_BUCKET"),
            secret("S3_ACCESS_KEY_ID"),
            secret("S3_SECRET_ACCESS_KEY"),
            prefix,
            cast(Literal["path", "virtual", "auto"], addressing_style),
            ttl,
            number("MAX_FILE_BYTES", "104857600"),
            max_age,
            log_level,
        )
