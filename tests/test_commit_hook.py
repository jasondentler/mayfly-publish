import subprocess
from pathlib import Path


def test_conventional_commits_hook(tmp_path: Path) -> None:
    hook = Path(__file__).resolve().parents[1] / ".githooks/commit-msg"
    message = tmp_path / "message"
    message.write_text("feat(storage): add staging\n")
    assert subprocess.run([str(hook), str(message)], check=False).returncode == 0  # noqa: S603
    message.write_text("misc update\n")
    assert subprocess.run([str(hook), str(message)], check=False, capture_output=True).returncode == 1  # noqa: S603
