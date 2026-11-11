"""Launch the optional OpenAI tunnel with its runtime key from the OS keyring."""

import argparse
import os
import sys

import keyring

from .errors import PublishError
from .runtime import DEFAULT_LIFETIME_SECONDS, lifetime_seconds, run_limited
from .settings import KEYRING_USERNAME, _keyring_secret

TUNNEL_KEYRING_SERVICE = "mayfly-publish-tunnel-api-key"
TUNNEL_PROFILE = "mayfly-publish"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the keyring-backed OpenAI tunnel runtime")
    parser.add_argument("action", choices=("store", "doctor", "run"))
    parser.add_argument("--lifetime-seconds", type=lifetime_seconds, default=DEFAULT_LIFETIME_SECONDS)
    args = parser.parse_args(argv)
    action = args.action

    try:
        if action == "store":
            value = os.environ.get("CONTROL_PLANE_API_KEY", "")
            if not value:
                raise PublishError("configuration", "CONTROL_PLANE_API_KEY is not set in this shell")
            backend = keyring.get_keyring()
            if not keyring.core.recommended(backend):
                raise PublishError("configuration", "No usable system keyring backend is available")
            backend.set_password(TUNNEL_KEYRING_SERVICE, KEYRING_USERNAME, value)
            print("Tunnel runtime key stored in the system keyring")
            return 0

        value = _keyring_secret(TUNNEL_KEYRING_SERVICE)
        environment = dict(os.environ)
        environment["CONTROL_PLANE_API_KEY"] = value
        command = ["tunnel-client", action, "--profile", TUNNEL_PROFILE]
        if action == "doctor":
            command.append("--explain")
            os.execvpe(command[0], command, environment)  # noqa: S606 - fixed executable and arguments, no shell
        return run_limited(command, environment, args.lifetime_seconds)
    except PublishError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
    except Exception:
        print("tunnel_unavailable: Could not access the system keyring or launch tunnel-client", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
