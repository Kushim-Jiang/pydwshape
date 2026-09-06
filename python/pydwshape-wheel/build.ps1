# build.ps1 — build the pydwshape wheel (Windows).
# Steps: build the Wine DWrite port -> copy winedwrite.dll into the package ->
#        ensure DWriteCore.dll -> maturin build.
param(
    [string]$Python = "C:\Softwares\Python\py313\python.exe"
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path          # python/pydwshape-wheel
$repo = (Resolve-Path (Join-Path $here "..\..")).Path           # repo root
$port = Join-Path $repo "tools\wine_dwrite\port"
$pkg  = Join-Path $here "python\pydwshape"

# 1) build the standalone Wine DWrite port (produces winedwrite.dll)
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $port "build.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 2) copy the port dll into the package so maturin bundles it
Copy-Item (Join-Path $port "build\winedwrite.dll") $pkg -Force
Write-Output ("bundled " + (Join-Path $pkg "winedwrite.dll"))

# 3) DWriteCore.dll must already sit next to the module (dwcore backend)
if (-not (Test-Path (Join-Path $pkg "DWriteCore.dll"))) {
    Write-Error "DWriteCore.dll missing in $pkg — copy it there first (see python/pydwshape-wheel/python/pydwshape/NOTICE.md)"
    exit 1
}

# 4) build the wheel (abi3)
Push-Location $here
& $Python -m maturin build --release -o dist
$rc = $LASTEXITCODE
Pop-Location
exit $rc
