#!/usr/bin/env bash
# build.sh — build the pydwshape wheel on Linux/macOS (cross-platform Wine
# DWrite backend). The Windows dwcore (DWriteCore) backend is not built here;
# the wheel still offers `backend="winedwrite"`.
#
# Requires: a C11 compiler (cc), make, and a Python env with maturin
# (`python -m pip install maturin`).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"                 # python/pydwshape-wheel
repo="$(cd "$here/../.." && pwd)"                     # repo root
port="$repo/tools/wine_dwrite/port"
pkg="$here/python/pydwshape"

# 1) build the standalone Wine DWrite port as a shared library
make -C "$port" lib

# 2) copy the port library into the package so maturin bundles it
libname="libwinedwrite.so"
if [ "$(uname)" = "Darwin" ]; then
    libname="libwinedwrite.dylib"
fi
cp "$port/$libname" "$pkg/$libname"
echo "bundled $pkg/$libname"

# 3) build the wheel (abi3)
python -m maturin build --release -o dist
