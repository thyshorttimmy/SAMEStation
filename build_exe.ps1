param(
    [switch]$OneFile = $true
)

$ErrorActionPreference = "Stop"

$python = "C:\Users\tyler\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $python)) {
    throw "Bundled Python runtime not found at $python"
}

Get-Process SAMEStation -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
if (Test-Path ".\dist\SAMEStation.exe") {
    Remove-Item ".\dist\SAMEStation.exe" -Force -ErrorAction SilentlyContinue
}

& $python -m pip install -r requirements.txt -r requirements-build.txt

$buildArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", "SAMEStation",
    "--windowed",
    "--collect-all", "imageio_ffmpeg",
    "--add-data", "web;web",
    "--add-data", "data\same_codes.json;data"
)

if ($OneFile) {
    $buildArgs += "--onefile"
}
else {
    $buildArgs += "--onedir"
}

$buildArgs += "samestation_launcher.py"

& $python @buildArgs

Write-Host ""
Write-Host "Build complete."
if ($OneFile) {
    Write-Host "EXE: dist\SAMEStation.exe"
}
else {
    Write-Host "Folder: dist\SAMEStation\"
}
