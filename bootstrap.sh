#!/usr/bin/env bash
# Build the pinned public A12 release without modifying upstream sources.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The build needs Python 3.12+ (tarfile extraction filters, hashlib.file_digest).
# A plain `python3` is often an older conda or system interpreter, so fall back
# to the newest versioned python3.N on PATH before giving up.
candidates="python3 $(compgen -c python3. | grep -E '^python3\.[0-9]+$' | sort -t. -k2,2 -rn | uniq || true)"
for candidate in $candidates; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    exec "$candidate" "$SCRIPT_DIR/scripts/bootstrap.py" "$@"
  fi
done
echo "Python 3.12+ is required; none of these qualify: $candidates" >&2
exit 1
