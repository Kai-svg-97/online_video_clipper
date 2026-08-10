#Requires -Version 5.1
param(
    [string]$AppVersion = ""   # 예: "1.2.3". 비어있으면 installer.iss 기본값 사용
)
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

# 2. YouTube OAuth Desktop 클라이언트 설정 검증 (값은 절대 출력하지 않음)
$oauthConfig = $env:OVC_YOUTUBE_OAUTH_CONFIG
if (-not $oauthConfig) {
    $oauthConfig = Join-Path $Root "data\OAuth2.json"
}
if (-not (Test-Path $oauthConfig)) {
    throw "OAuth 설정 파일을 찾을 수 없습니다: $oauthConfig"
}
try {
    $oauthJson = Get-Content -LiteralPath $oauthConfig -Raw | ConvertFrom-Json
} catch {
    throw "OAuth 설정 JSON을 파싱할 수 없습니다: $oauthConfig"
}
$installed = $oauthJson.installed
if (-not $installed) {
    throw "Desktop installed OAuth 설정이 아닙니다: $oauthConfig"
}
foreach ($field in @("client_id", "client_secret")) {
    $value = $installed.$field
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "OAuth 설정 필드가 없습니다: $field ($oauthConfig)"
    }
}
$redirects = @($installed.redirect_uris)
$hasLoopback = $redirects | Where-Object { $_ -like "http://localhost*" -or $_ -like "http://127.0.0.1*" }
if (-not $hasLoopback) {
    throw "localhost loopback redirect가 없습니다: $oauthConfig"
}
Write-Host "OAuth 설정 확인됨: $oauthConfig"

# 3. PyInstaller — 위에서 검증한 OAuth 설정 경로만 이 프로세스에 한정해 주입한다
$prevOauthEnv = $env:OVC_YOUTUBE_OAUTH_CONFIG
$env:OVC_YOUTUBE_OAUTH_CONFIG = $oauthConfig
try {
    Push-Location $Root
    python -m PyInstaller packaging/online_video_clipper.spec `
        --distpath dist/windows `
        --workpath build/tmp `
        --noconfirm
    Pop-Location
} finally {
    if ($null -eq $prevOauthEnv) {
        Remove-Item Env:\OVC_YOUTUBE_OAUTH_CONFIG -ErrorAction SilentlyContinue
    } else {
        $env:OVC_YOUTUBE_OAUTH_CONFIG = $prevOauthEnv
    }
}

# 4. Inno Setup
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    $issArgs = @((Join-Path $Root "packaging\installer.iss"))
    if ($AppVersion -ne "") {
        $issArgs = @("/DAppVersion=$AppVersion") + $issArgs
    }
    & $iscc @issArgs
    Write-Host "Installer: dist\YouTubeContentManager-setup.exe"
} else {
    Write-Warning "Inno Setup not found — skipping installer creation."
    Write-Host "Standalone exe: dist\windows\YouTubeContentManager.exe"
}
