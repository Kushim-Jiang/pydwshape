# NOTICE — Wine DWrite port licensing

`tools/wine_dwrite/wine-src/` contains unmodified source files from the Wine
project (<https://github.com/wine-mirror/wine>), specifically
`dlls/dwrite/`. Wine is licensed under the **GNU Lesser General Public License
v2.1 or later** (see `wine-src/dlls/dwrite/*.c` file headers, `COPYING.LIB` in
the upstream tree).

The standalone port in `tools/wine_dwrite/port/` is derived from those LGPL
files and is therefore distributed under the **same LGPL-2.1-or-later**
terms. This is intentional and mirrors how pyusp ships its standalone
`wineusp.dll` (Wine Uniscribe port) as a separate LGPL component alongside an
MIT core.

pydwshape (the Rust/Python core) remains MIT-licensed; it *loads* the port as
a separate dynamically-linked component and does not incorporate its code.

See upstream Wine `LICENSE`/`COPYING.LIB` for the full license text; a copy is
kept at `tools/wine_dwrite/wine-src/LICENSE`.
