#Requires -Version 5.1
# bin\deno.exe 를 scripts\deno_version.txt 에 고정된 버전으로 맞춘다.
# build_windows.ps1 과 .github/workflows/release.yml 이 함께 쓴다(버전 상수 한 곳).
# - 이미 같은 버전이면 아무것도 하지 않는다. 다르거나 없으면 다시 받는다.
# - 압축 파일의 SHA256 이 고정 해시와 다르면 실패한다(조용히 다른 바이너리가 번들되는 것을 막는다).
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
$cfg = @{}
foreach ($line in Get-Content (Join-Path $PSScriptRoot "deno_version.txt")) {
    if ($line -match '^\s*([a-z0-9_]+)\s*=\s*(\S+)\s*$') { $cfg[$Matches[1]] = $Matches[2] }
}
$version = $cfg["version"]
$expectedHash = $cfg["sha256"]
if (-not $version -or -not $expectedHash) { throw "deno_version.txt 에 version/sha256 이 없습니다" }

$denoExe = Join-Path $Root "bin\deno.exe"
if (Test-Path $denoExe) {
    $current = (& $denoExe --version | Select-Object -First 1)
    if ($current -match "deno\s+$([regex]::Escape($version))\b") {
        Write-Host "deno $version 확인됨: $denoExe"
        return
    }
    Write-Host "deno 버전이 다릅니다($current) — $version 으로 다시 받습니다"
}

$work = Join-Path $env:TEMP ("deno_dl_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
    $zip = Join-Path $work "deno.zip"
    $url = "https://github.com/denoland/deno/releases/download/v$version/deno-x86_64-pc-windows-msvc.zip"
    Write-Host "Downloading deno $version..."
    Invoke-WebRequest -Uri $url -OutFile $zip
    $actual = (Get-FileHash $zip -Algorithm SHA256).Hash
    if ($actual -ne $expectedHash) {
        throw "deno SHA256 불일치: 기대 $expectedHash, 실제 $actual"
    }
    Expand-Archive -Path $zip -DestinationPath $work -Force
    $found = Join-Path $work "deno.exe"
    if (-not (Test-Path $found)) { throw "압축 안에 deno.exe 가 없습니다" }
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "bin") | Out-Null
    Copy-Item $found $denoExe -Force
    Write-Host "deno placed at $denoExe"
} finally {
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
