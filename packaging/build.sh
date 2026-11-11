#!/usr/bin/env bash
# Build the FlagPole Linux (or macOS) app. Run from anywhere.
#   packaging/build.sh            -> dist/FlagPole/ (folder) + dist/FlagPole-linux.tar.gz
#   ONEFILE=1 packaging/build.sh  -> dist/FlagPole (single file)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .build-venv
. .build-venv/bin/activate
pip install --upgrade pip >/dev/null
pip install ./backend pyinstaller
if [ "${ONEFILE:-0}" = "1" ]; then
  FLAGPOLE_ONEFILE=1 pyinstaller --noconfirm flagpole.spec
  echo "Built dist/FlagPole"
else
  pyinstaller --noconfirm flagpole.spec
  tar -czf dist/FlagPole-linux.tar.gz -C dist FlagPole
  echo "Built dist/FlagPole/ and dist/FlagPole-linux.tar.gz"
fi
