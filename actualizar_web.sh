#!/usr/bin/env sh
set -e
EXCEL="${1:-collection.xlsx}"
python scripts/build_all.py --excel "$EXCEL"
