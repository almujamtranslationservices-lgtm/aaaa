#!/usr/bin/env bash
# Bootstrap the development environment (Python venv + dependencies).
# Includes the optional Qt headless stubs for GUI tests in containers.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Headless containers only (missing libGL etc.). Safe no-op on real desktops.
if ! .venv/bin/python -c "from PySide6.QtWidgets import QApplication" 2>/dev/null; then
    echo "PySide6 system libraries missing — building headless stubs…"
    bash scripts/setup_qt_stubs.sh .venv/bin/python /usr/local/lib || true
fi

echo
echo "✅ Dev environment ready."
echo "   Activate with:  source .venv/bin/activate"
echo "   Run tests with: python -m pytest"
echo "   Launch GUI:     python app.py gui"
echo "   Diagnostics:    python app.py doctor"
