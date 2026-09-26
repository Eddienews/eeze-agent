#!/usr/bin/env bash
# Eeze Agent dev check — lint + tests.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check .
uv run pytest -q
