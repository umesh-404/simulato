#!/bin/bash
# Compatibility wrapper (canonical entrypoint is repo-root start_pi.sh)
#
# Some guides and users run: bash scripts/start_pi.sh
# To avoid duplicate logic and drift, this script delegates to:
#   <repo_root>/start_pi.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

exec "$PROJECT_DIR/start_pi.sh"
