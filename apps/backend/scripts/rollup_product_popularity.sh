#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

cd "$BACKEND_DIR"

WINDOW_DAYS="${POPULARITY_ROLLUP_WINDOW_DAYS:-7}"
set -- --window-days "$WINDOW_DAYS" "$@"

if [ "${POPULARITY_ROLLUP_DRY_RUN:-false}" = "true" ]; then
  set -- --dry-run "$@"
fi

if [ -n "${POPULARITY_ROLLUP_COMPUTED_AT:-}" ]; then
  set -- --computed-at "$POPULARITY_ROLLUP_COMPUTED_AT" "$@"
fi

python -m app.cli.rollup_product_popularity "$@"
