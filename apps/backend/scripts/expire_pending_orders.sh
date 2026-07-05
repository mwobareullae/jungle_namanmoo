#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

cd "$BACKEND_DIR"

LIMIT="${PAYMENT_EXPIRY_SWEEP_LIMIT:-100}"
set -- --limit "$LIMIT" "$@"

if [ "${PAYMENT_EXPIRY_SWEEP_DRY_RUN:-false}" = "true" ]; then
  set -- --dry-run "$@"
fi

if [ -n "${PAYMENT_EXPIRY_SWEEP_NOW:-}" ]; then
  set -- --now "$PAYMENT_EXPIRY_SWEEP_NOW" "$@"
fi

python -m app.cli.expire_pending_orders "$@"
