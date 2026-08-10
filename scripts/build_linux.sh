#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$ROOT/bin"
FFMPEG="$BIN_DIR/ffmpeg"

# 1. Download static ffmpeg for Linux if missing
if [ ! -f "$FFMPEG" ]; then
    echo "Downloading ffmpeg for Linux..."
    mkdir -p "$BIN_DIR"
    TMP=$(mktemp -d)
    curl -L "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
         -o "$TMP/ffmpeg.tar.xz"
    tar -xf "$TMP/ffmpeg.tar.xz" -C "$TMP"
    cp "$TMP"/ffmpeg-*/ffmpeg "$FFMPEG"
    chmod +x "$FFMPEG"
    echo "ffmpeg placed at $FFMPEG"
fi

# 2. YouTube OAuth Desktop 클라이언트 설정 검증 (값은 절대 출력하지 않음)
OAUTH_CONFIG="${OVC_YOUTUBE_OAUTH_CONFIG:-$ROOT/data/OAuth2.json}"
python3 - "$OAUTH_CONFIG" <<'PYEOF'
import json
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except OSError:
    sys.exit(f"OAuth 설정 파일을 읽을 수 없습니다: {path}")
except json.JSONDecodeError:
    sys.exit(f"OAuth 설정 JSON을 파싱할 수 없습니다: {path}")

installed = data.get("installed") if isinstance(data, dict) else None
if not isinstance(installed, dict):
    sys.exit(f"Desktop installed OAuth 설정이 아닙니다: {path}")
for field in ("client_id", "client_secret"):
    if not isinstance(installed.get(field), str) or not installed[field].strip():
        sys.exit(f"OAuth 설정 필드가 없습니다: {field} ({path})")
redirects = installed.get("redirect_uris")
if not isinstance(redirects, list) or not any(
    isinstance(u, str) and u.startswith(("http://localhost", "http://127.0.0.1"))
    for u in redirects
):
    sys.exit(f"localhost loopback redirect가 없습니다: {path}")
PYEOF
echo "OAuth 설정 확인됨: $OAUTH_CONFIG"
export OVC_YOUTUBE_OAUTH_CONFIG="$OAUTH_CONFIG"

# 3. PyInstaller
cd "$ROOT"
pyinstaller packaging/online_video_clipper.spec \
    --distpath dist/linux \
    --workpath build/tmp \
    --noconfirm

# 4. AppImage
APPDIR="$ROOT/build/AppDir"
mkdir -p "$APPDIR/usr/bin"
cp dist/linux/YouTubeContentManager "$APPDIR/usr/bin/"

cat > "$APPDIR/YouTubeContentManager.desktop" <<EOF
[Desktop Entry]
Name=YouTube Content Manager
Exec=YouTubeContentManager
Icon=icon
Type=Application
Categories=Network;Video;
EOF

if [ -f "$ROOT/assets/icon.png" ]; then
    cp "$ROOT/assets/icon.png" "$APPDIR/icon.png"
fi

if command -v appimagetool &>/dev/null; then
    appimagetool "$APPDIR" dist/YouTubeContentManager-x86_64.AppImage
    echo "AppImage: dist/YouTubeContentManager-x86_64.AppImage"
else
    echo "appimagetool not found — skipping AppImage creation."
    echo "Standalone binary: dist/linux/YouTubeContentManager"
fi
