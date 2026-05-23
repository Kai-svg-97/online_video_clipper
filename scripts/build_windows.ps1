#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent

# 1. Download ffmpeg for Windows if missing
$ffmpegExe = Join-Path $Root "bin\ffmpeg.exe"
if (-not (Test-Path $ffmpegExe)) {
    Write-Host "Downloading ffmpeg for Windows..."
    $tmpZip = Join-Path $env:TEMP "ffmpeg.zip"
    $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Invoke-WebRequest -Uri $url -OutFile $tmpZip
    Expand-Archive -Path $tmpZip -DestinationPath (Join-Path $env:TEMP "ffmpeg_extract") -Force
    $ffmpegBin = Get-ChildItem (Join-Path $env:TEMP "ffmpeg_extract") -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "bin") | Out-Null
    Copy-Item $ffmpegBin.FullName $ffmpegExe
    Write-Host "ffmpeg placed at $ffmpegExe"
}

# 2. PyInstaller
Push-Location $Root
pyinstaller packaging/online_video_clipper.spec `
    --distpath dist/windows `
    --workpath build/tmp `
    --noconfirm
Pop-Location

# 3. Inno Setup
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc (Join-Path $Root "packaging\installer.iss")
    Write-Host "Installer: dist\YouTubeContentManager-setup.exe"
} else {
    Write-Warning "Inno Setup not found — skipping installer creation."
    Write-Host "Standalone exe: dist\windows\YouTubeContentManager.exe"
}
