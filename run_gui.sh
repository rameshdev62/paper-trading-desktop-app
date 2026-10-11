#!/usr/bin/env bash
# Launcher for Nifty 50 Paper Trader Desktop Backtesting Lab
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -f ".venv/bin/python3" ]; then
    PYTHON_EXEC=".venv/bin/python3"
else
    PYTHON_EXEC="python3"
fi

echo "Launching Nifty 50 Historical Backtesting Lab Desktop Application..."
exec "$PYTHON_EXEC" app_gui.py "$@"
