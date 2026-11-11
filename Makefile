.PHONY: setup serve python-version test lint type check fmt smoke cleanup-dry-run keyring-set tunnel-keyring-import tunnel-doctor tunnel-run install-git-hooks

setup:
	uv python install 3.15
	uv sync --locked --extra dev --python 3.15
	@.venv/bin/python -m mayfly_publish.setup

serve:
	@.venv/bin/python -m mayfly_publish.tunnel run --lifetime-seconds $(or $(LIFETIME_SECONDS),3600)

python-version:
	.venv/bin/python -c 'import sys; assert sys.version_info >= (3, 15, 2), "Python 3.15.2 or newer required"'

test:
	.venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

type:
	.venv/bin/mypy

check: python-version lint type test

fmt:
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .

smoke:
	scripts/smoke-test.sh

cleanup-dry-run:
	.venv/bin/mayfly-publish cleanup --dry-run

keyring-set:
	@.venv/bin/python -m mayfly_publish.credentials

tunnel-keyring-import:
	@.venv/bin/python -m mayfly_publish.tunnel store

tunnel-doctor:
	@.venv/bin/python -m mayfly_publish.tunnel doctor

tunnel-run: serve

install-git-hooks:
	git config core.hooksPath .githooks
