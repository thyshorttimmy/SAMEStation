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
if (Test-Path ".\dist\SAMEStation Installer.exe") {
    Remove-Item ".\dist\SAMEStation Installer.exe" -Force -ErrorAction SilentlyContinue
}

$git = Get-Command git -ErrorAction SilentlyContinue
$versionTag = "local-build"
$commit = ""
$branch = ""
if ($git) {
    try { $versionTag = (& $git.Source describe --tags --always --dirty).Trim() } catch {}
    try { $commit = (& $git.Source rev-parse HEAD).Trim() } catch {}
    try { $branch = (& $git.Source rev-parse --abbrev-ref HEAD).Trim() } catch {}
}

$buildInfo = @{
    appName = "SAMEStation"
    versionTag = $versionTag
    commit = $commit
    sourceBranch = $branch
    builtAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    repoOwner = "thyshorttimmy"
    repoName = "SAMEStation"
}
$buildInfo | ConvertTo-Json | Set-Content -Path ".\build_info.json" -Encoding UTF8

& $python -m pip install -r requirements.txt -r requirements-build.txt

function New-BuildArgs {
    param(
        [string]$Name,
        [string]$EntryPoint
    )

    $args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", $Name,
    "--icon", "web\\samestation.ico",
    "--windowed",
    "--collect-all", "imageio_ffmpeg",
    "--add-data", "web;web",
    "--add-data", "data\same_codes.json;data",
    "--add-data", "build_info.json;."
    )

    if ($OneFile) {
        $args += "--onefile"
    }
    else {
        $args += "--onedir"
    }

    $args += $EntryPoint
    return $args
}

& $python @(New-BuildArgs -Name "SAMEStation" -EntryPoint "samestation_launcher.py")
& $python @(New-BuildArgs -Name "SAMEStation Installer" -EntryPoint "samestation_installer.py")

Write-Host ""
Write-Host "Build complete."
if ($OneFile) {
    Write-Host "EXE: dist\SAMEStation.exe"
    Write-Host "Installer: dist\SAMEStation Installer.exe"
}
else {
    Write-Host "Folder: dist\SAMEStation\"
    Write-Host "Folder: dist\SAMEStation Installer\"
}
