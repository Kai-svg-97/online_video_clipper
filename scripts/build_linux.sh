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

# 2. PyInstaller
cd "$ROOT"
pyinstaller packaging/online_video_clipper.spec \
    --distpath dist/linux \
    --workpath build/tmp \
    --noconfirm

# 3. AppImage
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
