#!/usr/bin/env bash
# AI Video Factory — release build (PHASE 17).
#
#   bash scripts/build_release.sh          # wheel (pip/pipx distribution)
#   bash scripts/build_release.sh --exe    # wheel + PyInstaller onedir bundle
#
# The wheel is the primary distribution: `pipx install ai_video_factory-*.whl`
# gives the `ai-video-factory` command (doctor | selftest | gui) with the
# bundled Cairo fonts and a static FFmpeg — zero system installs.
#
# The PyInstaller bundle additionally needs a Python built WITH
# --enable-shared (libpython3.x.so present); the sandbox python is static-only,
# so --exe is intended for normal dev machines (see README §التوزيع).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Cleaning previous artifacts"
rm -rf build dist wheels
mkdir -p wheels

echo "==> Building wheel (pip distribution)"
python3 -m venv .venv 2>/dev/null || true
".venv/bin/pip" install -q --upgrade pip setuptools wheel
".venv/bin/pip" wheel . --no-deps -w wheels
echo "    wheels/:"
ls -1 wheels

if [[ "${1:-}" == "--exe" ]]; then
    echo "==> Checking PyInstaller prerequisites (libpython must be shared)"
    if ! ".venv/bin/python" - <<'PY'
import sys, sysconfig, pathlib
instso = sysconfig.get_config_var("INSTSONAME")
libdir = sysconfig.get_config_var("LIBDIR")
ok = instso and any((pathlib.Path(p) / instso).exists()
                    for p in (libdir, sys.prefix + "/lib", "."))
sys.exit(0 if ok else 1)
PY
    then
        echo "    ERROR: libpython shared library not found."
        echo "    Install a Python built with --enable-shared (e.g. apt install libpython3.11)"
        echo "    or distribute the wheel (default mode)."
        exit 1
    fi
    echo "==> Building PyInstaller onedir bundle"
    ".venv/bin/pip" install -q pyinstaller
    ".venv/bin/pyinstaller" release.spec --noconfirm
    echo "    dist/AIVideoFactory/AIVideoFactory doctor   # smoke test it"
fi

echo "==> Done."
echo "    Install:  pipx install wheels/ai_video_factory-*.whl"
echo "    Run:      ai-video-factory doctor | selftest | gui"
