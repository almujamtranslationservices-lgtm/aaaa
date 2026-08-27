#!/usr/bin/env bash
# Headless-sandbox helper: build stub shared libraries for the system libs that
# PySide6 links against but that are missing in minimal containers
# (libGL.so.1, libEGL.so.1, libxkbcommon.so.0, libdbus-1.so.3 …).
#
# The stubs export the exact symbols Qt references (offscreen/raster platform
# never actually calls into GL), so GUI tests can run without a display stack.
# On a real desktop with a normal graphics stack this script is NOT needed.
set -euo pipefail

SITE=$("$1" -c "import PySide6, os; print(os.path.dirname(os.path.dirname(PySide6.__file__)))")
OUT=$(mktemp -d)
SYMS="$OUT/syms.txt"

# 1) Collect every undefined symbol from PySide6/Qt objects & plugins.
find "$SITE/PySide6" -name "*.so" -o -name "*.so.*" | while read -r so; do
    nm -D --undefined-only "$so" 2>/dev/null || true
done | awk '{print $NF}' | sort -u > "$SYMS"

# 2) Filter to symbols that belong to the missing system libs.
grep -E '^(gl[A-Z]|glX|egl[A-Z]|xkb_|dbus_|xcb_|xcb)' "$SYMS" | sort -u > "$OUT/stub_syms.c.list" || true

{
    echo "/* Auto-generated stub exports for headless Qt (offscreen platform). */"
    while read -r sym; do
        sym="${sym%%@*}"   # drop symbol-version suffix (e.g. name@V_0.5.0)
        echo "void $sym(void) { /* stub */ }"
    done < "$OUT/stub_syms.c.list"
} > "$OUT/stub.c"

gcc -shared -fPIC -o "$OUT/libavfqtstub.so.1" "$OUT/stub.c"

# 3) Install the same stub under every missing soname.
MISSING=$(find "$SITE/PySide6" \( -name "*.so" -o -name "*.so.*" \) -exec ldd {} + 2>/dev/null \
          | grep "not found" | awk '{print $1}' | sort -u)

if [ -z "$MISSING" ]; then
    echo "No missing Qt system libraries — stubs not needed."
    exit 0
fi

DEST=${2:-/usr/local/lib}
for soname in $MISSING; do
    case "$soname" in
        libGL*|libEGL*|libxkbcommon*|libdbus*|libxcb*|libX*) cp "$OUT/libavfqtstub.so.1" "$DEST/$soname" ;;
        *) echo "NOTE: leaving $soname unstubbed (not a known headless-safe lib)"; continue ;;
    esac
    echo "stubbed -> $DEST/$soname"
done
ldconfig 2>/dev/null || sudo ldconfig
echo "Qt stubs ready in $DEST"
