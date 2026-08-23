#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --metaeditor /path/to/metaeditor.exe --source /path/to/LicensedEA.mq4|mq5"
  exit 2
}

METAEDITOR=""
SOURCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --metaeditor) METAEDITOR="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    *) usage ;;
  esac
done

[[ -n "$METAEDITOR" && -n "$SOURCE" ]] || usage
[[ -f "$METAEDITOR" ]] || { echo "MetaEditor not found: $METAEDITOR" >&2; exit 1; }
[[ -f "$SOURCE" ]] || { echo "MQL source not found: $SOURCE" >&2; exit 1; }

SOURCE="$(realpath "$SOURCE")"
LOG="${SOURCE%.*}.compile.log"

if command -v wine64 >/dev/null 2>&1; then
  WINE_BIN="wine64"
elif command -v wine >/dev/null 2>&1; then
  WINE_BIN="wine"
else
  echo "Wine is not installed. Install Wine or run this helper on a Windows MetaTrader build host." >&2
  exit 1
fi

"$WINE_BIN" "$METAEDITOR" "/compile:$SOURCE" "/log:$LOG"

OUTPUT="${SOURCE%.*}.ex4"
[[ "${SOURCE##*.}" == "mq5" ]] && OUTPUT="${SOURCE%.*}.ex5"
if [[ ! -f "$OUTPUT" ]]; then
  echo "Compilation did not produce $OUTPUT. Inspect $LOG for MetaEditor errors." >&2
  exit 1
fi

echo "Built: $OUTPUT"
echo "Compiler log: $LOG"
