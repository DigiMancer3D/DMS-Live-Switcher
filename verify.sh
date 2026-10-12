#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m compileall -q dms_live_switcher.py switch_core.py dms_live_deck_bridge.py scripts/install_bridges.py
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 scripts/install_bridges.py "$@"
