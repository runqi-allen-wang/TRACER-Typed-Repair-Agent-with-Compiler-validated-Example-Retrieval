#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT="$SCRIPT_DIR"
while [ "$REPOSITORY_ROOT" != "/" ] && [ ! -f "$REPOSITORY_ROOT/leancapsule/__main__.py" ]; do REPOSITORY_ROOT=$(dirname -- "$REPOSITORY_ROOT"); done
if [ -f "$REPOSITORY_ROOT/leancapsule/__main__.py" ]; then cd "$REPOSITORY_ROOT"; fi
python -m leancapsule replay "$SCRIPT_DIR"
