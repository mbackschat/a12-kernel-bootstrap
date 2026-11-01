#!/usr/bin/env bash
# Build the pinned public A12 release without modifying upstream sources.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/scripts/bootstrap.py" "$@"
