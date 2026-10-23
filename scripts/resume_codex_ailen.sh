#!/usr/bin/env bash
set -euo pipefail

THREAD_ID="01a03a1f-e86e-7213-9581-af295af5c7f1"
AGENT="${1:-sol}"
if [[ $# -gt 0 ]]; then shift; fi

case "$AGENT" in
  sol)
    exec codex resume "$THREAD_ID" "$@"
    ;;
  luna)
    exec codex -m gpt-6-luna -c model_reasoning_effort='"high"' resume "$THREAD_ID" "$@"
    ;;
  *)
    printf 'Uso: %s [sol|luna] [opciones de codex resume...]\n' "$0" >&2
    exit 2
    ;;
esac
