"""Interactively store S3 credentials under the service names in .env."""

import getpass
import os
import re
import sys
from pathlib import Path

import keyring

from .errors import PublishError
from .settings import KEYRING_USERNAME, _dotenv


def main() -> int:
    try:
        data = _dotenv(Path.cwd() / ".env") | dict(os.environ)
        access_service = data.get("S3_ACCESS_KEY_ID_KEYRING_SERVICE", "")
        secret_service = data.get("S3_SECRET_ACCESS_KEY_KEYRING_SERVICE", "")
        for service in (access_service, secret_service):
            if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", service):
                raise PublishError("configuration", "Configure both S3 keyring service names in .env")
        if access_service == secret_service:
            raise PublishError("configuration", "S3 keyring service names must be distinct")
        backend = keyring.get_keyring()
        if not keyring.core.recommended(backend):
            raise PublishError("configuration", "No usable system keyring backend is available")
        access_key = getpass.getpass("S3 access key ID: ")
        secret_key = getpass.getpass("S3 secret access key: ")
        if not access_key or not secret_key:
            raise PublishError("configuration", "Both S3 credentials are required")
        backend.set_password(access_service, KEYRING_USERNAME, access_key)
        backend.set_password(secret_service, KEYRING_USERNAME, secret_key)
        print("S3 credentials stored in the system keyring")
        return 0
    except PublishError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
    except Exception:
        print("keyring_unavailable: Could not store S3 credentials", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
