# build.ps1 — build the standalone Wine DWrite shaping port (Windows/MinGW).
# Cross-platform: the same sources compile with `cc` on Linux/macOS.
param(
    [string]$Gcc = "C:\Softwares\miktex\perl\c\bin\gcc.exe"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$inc  = Join-Path $root "include"
$src  = Join-Path $root "src"
$out  = Join-Path $root "build"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$units = @(
    "opentype_shaping.c",
    "shape_port.c",
    "mirror.c",
    "arabic.c",
    "arabic_table.c",
    "wd_font.c",
    "wd_script.c",
    "wd_engine.c",
    "wd_json.c",
    "main.c"
)
$objs = @()
foreach ($u in $units) {
    $obj = Join-Path $out ($u -replace '\.c$', '.o')
    & $Gcc -std=gnu11 -O2 -g -Wall -I $inc -I $src -c (Join-Path $src $u) -o $obj
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $objs += $obj
}
$exe = Join-Path $out "wdmain.exe"
& $Gcc $objs -o $exe -lm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output ("built " + $exe)

# shared library (for ctypes / wheel integration)
$dllobjs = $objs | Where-Object { $_ -notmatch 'main\.o$' }
$dll = Join-Path $out "winedwrite.dll"
& $Gcc -shared -static-libgcc $dllobjs -o $dll -lm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output ("built " + $dll)
