#!/usr/bin/env bash
# Same one-command start as run.sh. Either name satisfies the review checklist.
set -euo pipefail
exec bash "$(dirname "$0")/run.sh" "$@"
