param(
    [switch]$OneFile = $true
)

$ErrorActionPreference = "Stop"

$python = "C:\Users\tyler\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $python)) {
    throw "Bundled Python runtime not found at $python"
}

Get-Process SAMEStation -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
@(
    ".\dist\SAMEStation Server.exe",
    ".\dist\SAMEStation Client.exe",
    ".\dist\SAMEStation Server Installer.exe",
    ".\dist\SAMEStation Client Installer.exe"
) | ForEach-Object {
    if (Test-Path $_) {
        Remove-Item $_ -Force -ErrorAction SilentlyContinue
    }
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

$payloadChannel = "stable"
if ($versionTag -match "alpha|beta|test|nightly|rc") {
    $payloadChannel = "nightly"
}

& $python -m pip install -r requirements.txt -r requirements-build.txt

function New-BuildArgs {
    param(
        [string]$Name,
        [string]$EntryPoint,
        [switch]$Console
    )

    $args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", $Name,
    "--icon", "web\\samestation.ico",
    "--collect-all", "imageio_ffmpeg",
    "--add-data", "web;web",
    "--add-data", "data\same_codes.json;data",
    "--add-data", "build_info.json;."
    )

    if ($Console) {
        $args += "--console"
    }
    else {
        $args += "--windowed"
    }

    if ($OneFile) {
        $args += "--onefile"
    }
    else {
        $args += "--onedir"
    }

    $args += $EntryPoint
    return $args
}

& $python @(New-BuildArgs -Name "SAMEStation Server" -EntryPoint "samestation_server.py")
& $python @(New-BuildArgs -Name "SAMEStation Client" -EntryPoint "samestation_client.py")
& $python @(New-BuildArgs -Name "SAMEStation Server Installer" -EntryPoint "samestation_server_installer.py")
& $python @(New-BuildArgs -Name "SAMEStation Client Installer" -EntryPoint "samestation_client_installer.py")

$publicReleaseDir = ".\dist\public-release"
$internalPayloadDir = ".\dist\internal-payloads"
New-Item -ItemType Directory -Path $publicReleaseDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $internalPayloadDir "stable") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $internalPayloadDir "nightly") -Force | Out-Null

Copy-Item ".\dist\SAMEStation Server Installer.exe" -Destination (Join-Path $publicReleaseDir "SAMEStation Server Installer.exe") -Force
Copy-Item ".\dist\SAMEStation Client Installer.exe" -Destination (Join-Path $publicReleaseDir "SAMEStation Client Installer.exe") -Force
Copy-Item ".\dist\SAMEStation Server.exe" -Destination (Join-Path $internalPayloadDir "$payloadChannel\SAMEStation Server.exe") -Force
Copy-Item ".\dist\SAMEStation Client.exe" -Destination (Join-Path $internalPayloadDir "$payloadChannel\SAMEStation Client.exe") -Force

Write-Host ""
Write-Host "Build complete."
if ($OneFile) {
    Write-Host "Server: dist\SAMEStation Server.exe"
    Write-Host "Client: dist\SAMEStation Client.exe"
    Write-Host "Server Installer: dist\SAMEStation Server Installer.exe"
    Write-Host "Client Installer: dist\SAMEStation Client Installer.exe"
    Write-Host "Public release assets: dist\public-release\"
    Write-Host "Internal payload assets: dist\internal-payloads\$payloadChannel\"
}
else {
    Write-Host "Folder: dist\SAMEStation Server\"
    Write-Host "Folder: dist\SAMEStation Client\"
    Write-Host "Folder: dist\SAMEStation Server Installer\"
    Write-Host "Folder: dist\SAMEStation Client Installer\"
}
