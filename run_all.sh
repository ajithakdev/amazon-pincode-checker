#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

ASIN="${1:-${ASIN:-B0B5V5VHB6}}"

for d in venv .venv; do
    if [ -f "$d/bin/activate" ]; then
        source "$d/bin/activate"
        break
    fi
done
if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "Error: no venv/ or .venv/ found. Create one and install requirements.txt." >&2
    exit 1
fi

echo "Running Tamil Nadu..."
python cli.py --asin "$ASIN" --pincodes data/tamil_nadu_pincodes.txt --resume
echo "Running Bengaluru..."
python cli.py --asin "$ASIN" --pincodes data/bengaluru_pincodes.txt --resume
echo "Done!"
