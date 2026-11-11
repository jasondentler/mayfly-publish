#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
"$project_dir/.venv/bin/python" -m pytest -q
"$project_dir/.venv/bin/ruff" check .
"$project_dir/.venv/bin/ruff" format --check .
"$project_dir/.venv/bin/mypy"
"$project_dir/.venv/bin/mayfly-publish" --help >/dev/null
