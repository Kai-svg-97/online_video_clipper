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
        # 프레임리스 타이틀바: `gui.frameless.win32_hook`은 **함수 안에서** 임포트되고
        # (비윈도우에서 `ctypes.windll` 때문에 모듈 로드가 실패하므로 지연시킨다),
        # 빠지면 설치가 조용히 실패해 OS 타이틀바로 되돌아간다 — 앱은 뜨지만 사용자가
        # 요청한 화면이 아니다. 윈도우 빌드에서만 명시한다.
        *(["gui.frameless.win32_hook"] if _win else []),
        # 클라우드 동기화: keyring 백엔드·msal·google API는 지연/동적 import라 명시 수집
        "keyring",
        *collect_submodules("keyring.backends"),
        *collect_submodules("msal"),
        "googleapiclient",
        "google_auth_oauthlib",
        # 음원 태깅: 포맷별 모듈을 함수 안에서 import 하고, `mutagen.File`은 런타임에
        # 핸들러(oggvorbis·oggopus 등)를 동적으로 고른다 — 정적 분석으로는 잡히지
        # 않아 빠지면 태깅이 **조용히** 실패한다(어댑터가 예외를 삼키는 설계라 더 그렇다).
        *collect_submodules("mutagen"),
        # 음성 인식: faster_whisper 는 ctranslate2·tokenizers·av 를 함수 안에서
        # 끌어오고, ctranslate2 는 네이티브 DLL 을 동적으로 연다.
        *collect_submodules("faster_whisper"),
        *collect_submodules("ctranslate2"),
        "av",
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
