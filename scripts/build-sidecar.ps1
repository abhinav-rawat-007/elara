# Builds the Python backend into a single elara-backend.exe and stages it as a
# Tauri sidecar. Run from anywhere:  .\scripts\build-sidecar.ps1
#
# After this, add the sidecar to src-tauri/tauri.conf.json for a bundled build:
#     "bundle": { "externalBin": ["binaries/elara-backend"], ... }
# then `pnpm tauri build`. (It's left out of the committed config so a plain
# `pnpm tauri dev` still works without building the sidecar first.)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Backend venv not found at $python — create it first (see README Setup)."
}

Write-Host "==> Ensuring PyInstaller is installed" -ForegroundColor Cyan
& $python -m pip install --quiet --disable-pip-version-check pyinstaller

Write-Host "==> Building elara-backend.exe (this pulls in whisper/kokoro — takes a while)" -ForegroundColor Cyan
Push-Location $backend
try {
    & $python -m PyInstaller --noconfirm --clean elara-backend.spec
} finally {
    Pop-Location
}

$built = Join-Path $backend "dist\elara-backend.exe"
if (-not (Test-Path $built)) {
    throw "Build did not produce $built"
}

# Tauri sidecars are named <name>-<target-triple>. Ask rustc for the host triple.
$triple = (& rustc -Vv | Select-String "^host: ").ToString().Split(" ")[1]
$destDir = Join-Path $root "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$dest = Join-Path $destDir "elara-backend-$triple.exe"
Copy-Item $built $dest -Force

Write-Host ""
Write-Host "Sidecar staged at: $dest" -ForegroundColor Green
Write-Host "Next: add `"externalBin`": [`"binaries/elara-backend`"] under `"bundle`" in" -ForegroundColor Green
Write-Host "src-tauri/tauri.conf.json, then run: pnpm tauri build" -ForegroundColor Green
