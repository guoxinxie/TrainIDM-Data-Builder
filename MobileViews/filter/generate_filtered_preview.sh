#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_PATH="${SCRIPT_DIR}/filter_mv_trace.csv"
ROOT_DIR="${SCRIPT_DIR}/mv_trace_en"
OUTPUT_HTML="${SCRIPT_DIR}/filter_mv_filtered_preview.html"
PY_SCRIPT="${SCRIPT_DIR}/generate_filtered_preview.py"

python3 "${PY_SCRIPT}" \
  --csv "${CSV_PATH}" \
  --root-dir "${ROOT_DIR}" \
  --output "${OUTPUT_HTML}"

echo "HTML generated at: ${OUTPUT_HTML}"
