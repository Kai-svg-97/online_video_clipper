# -*- mode: python ; coding: utf-8 -*-
import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

_win = platform.system() == "Windows"
# spec 파일은 packaging/ 기준이므로 루트 bin/으로 한 단계 올라간다
_ffmpeg_src = "../bin/ffmpeg.exe" if _win else "../bin/ffmpeg"
_icon = "assets/icon.ico" if _win else "assets/icon.png"

# YouTube Desktop OAuth 클라이언트 설정 — 빌드 스크립트가 검증 후 주입한다.
# 값을 여기서 읽거나 출력하지 않고 파일 경로만 다룬다.
_oauth_src = os.environ.get("OVC_YOUTUBE_OAUTH_CONFIG")
if not _oauth_src or not Path(_oauth_src).is_file():
    raise SystemExit("OVC_YOUTUBE_OAUTH_CONFIG must point to an installed-app JSON file")

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[(_ffmpeg_src, "bin")],
    datas=[
        ("../assets",  "assets"),
        ("../db",      "db"),
        (_oauth_src,   "config"),
        *collect_data_files("yt_dlp"),
        *collect_data_files("PyQt6"),
    ],
    hiddenimports=[
        *collect_submodules("yt_dlp"),
        "PyQt6.sip",
        "sqlite3",
        # 클라우드 동기화: keyring 백엔드·msal·google API는 지연/동적 import라 명시 수집
        "keyring",
        *collect_submodules("keyring.backends"),
        *collect_submodules("msal"),
        "googleapiclient",
        "google_auth_oauthlib",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    [],
    name="YouTubeContentManager",
    debug=False,
    console=False,
    icon=f"../{_icon}",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="YouTubeContentManager",
)
