"""상세 설명서에 넣을 화면 갈무리를 만든다 — `docs/manual/images/*.png`.

**왜 스크립트인가**: 손으로 찍은 갈무리는 화면이 바뀌면 조용히 낡는다. 여기서는
임시 데이터 디렉터리에 표본 자료를 심고 실제 앱 화면을 그려 저장하므로, UI가 바뀌면
다시 돌리기만 하면 된다.

**사용자의 실제 자료는 건드리지도, 찍히지도 않는다.** 이를 위해 DB만이 아니라
**데이터 디렉터리 전체**를 `OVC_DATA_DIR` 로 갈아끼운다 — DB만 임시본으로 바꾸는
것으로는 부족했다. `data/config.yaml` 에는 태그 목록(`hidden_tag_names`)과 브라우저
프로필 경로(`yt_auth_profile`, 사용자 이름이 들어간다) 같은 개인적인 값이 있고,
실제로 v1.32.0 갈무리에 사용자의 태그가 찍혀 나갔다.

환경 변수는 **`config.settings` 가 임포트되기 전에** 설정해야 한다(경로 상수가 모듈을
불러올 때 정해진다). 그래서 이 파일은 맨 위에서 환경 변수를 세우고, 무거운 임포트는
전부 `main()` 안으로 미룬다 — 위쪽에 앱 모듈 임포트를 추가하면 격리가 조용히 깨진다.

사용:
    python scripts/capture_screenshots.py

주의: `QWidget.grab()`은 창을 화면에 띄우지 않고도 그려 낸다. 창을 실제로 띄우면
    테마·애니메이션이 자리 잡기 전에 찍힐 수 있어 오히려 결과가 불안정하다.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# ── 격리: 앱 모듈을 하나라도 불러오기 전에 세운다 ──────────────────────────
# (이 줄 위로 앱 모듈을 임포트하면 사용자의 실제 설정이 읽힌다.)
#
# 시스템 임시 폴더가 아니라 **프로젝트 안**에 둔다 — 설정 화면이 저장 경로를 그대로
# 보여 주는데, 윈도우의 임시 폴더는 사용자 홈 아래라 갈무리에 **사용자 이름이 찍힌다**
# (실제로 그렇게 나왔다). `build/` 는 빌드 산출물 자리라 git이 무시한다.
_SANDBOX = _ROOT / "build" / "manual-sandbox"
shutil.rmtree(_SANDBOX, ignore_errors=True)    # 지난 회차가 남아 있으면 지운다
_SANDBOX.mkdir(parents=True, exist_ok=True)
os.environ["OVC_DATA_DIR"] = str(_SANDBOX)
assert "config.settings" not in sys.modules, "설정이 이미 로드됐다 — 격리가 깨졌다"

OUT_DIR = _ROOT / "docs" / "manual" / "images"
WINDOW_SIZE = (1280, 800)


def _seed(db) -> None:
    """설명서에 보일 만큼의 표본 자료. 실제 사람·채널이 아닌 가상의 값만 쓴다."""
    import uuid
    from datetime import datetime, timedelta

    now = datetime.now()
    cats = [("개발 노트", None), ("음악 창고", None), ("일상 기록", None)]
    rows = [
        ("파이썬으로 만드는 데스크톱 앱 1편", "개발 노트", 1523, 0, 1),
        ("파이썬으로 만드는 데스크톱 앱 2편", "개발 노트", 2140, 1, 0),
        ("한 시간 만에 배우는 SQLite",        "개발 노트", 3605, 0, 0),
        ("퇴근길에 듣는 재즈 모음",           "음악 창고", 4812, 1, 1),
        ("주말 캠핑 브이로그",                "일상 기록", 962,  0, 0),
        ("겨울 산행 기록 — 설악산",           "일상 기록", 1780, 0, 0),
    ]
    with db.connection() as conn:
        cat_ids: dict[str, str] = {}
        for name, parent in cats:
            cid = uuid.uuid4().hex
            cat_ids[name] = cid
            conn.execute(
                "INSERT INTO categories (id, name, parent_id) VALUES (?, ?, ?)",
                (cid, name, parent),
            )
        for i, (title, channel, duration, watched, favorite) in enumerate(rows):
            stamp = (now - timedelta(days=i * 3)).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO videos (id, url, title, channel_name, duration_sec, "
                "favorite, watched, last_position_ms, notes, gemini_summary, "
                "thumbnail_path, category_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', '', '', ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    f"https://www.youtube.com/watch?v=sample{i:04d}",
                    title, channel, duration, favorite, watched,
                    cat_ids[channel], stamp, stamp,
                ),
            )
        # 다운로드 화면이 비어 있으면 설명서로 쓸 수 없다 — 이력도 함께 심는다.
        done = [
            ("파이썬으로 만드는 데스크톱 앱 1편", "1080p", "mp4", "completed", 412_530_176, ""),
            ("퇴근길에 듣는 재즈 모음",           "best",  "mp3", "completed",  92_341_760, ""),
            ("주말 캠핑 브이로그",                "720p",  "mp4", "failed",              0,
             "네트워크 연결이 끊어졌습니다"),
        ]
        for i, (title, quality, fmt, status, size, err) in enumerate(done):
            stamp = (now - timedelta(hours=i * 5)).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO download_history (id, url, title, quality, format, "
                "subtitle_langs, include_thumbnail, include_metadata, status, file_path, "
                "file_size_bytes, error_msg, retry_count, gemini_summary, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, '', 1, 1, ?, ?, ?, ?, 0, '', ?, ?)",
                (
                    uuid.uuid4().hex,
                    f"https://www.youtube.com/watch?v=sample{i:04d}",
                    title, quality, fmt, status,
                    f"downloads/{title}.{fmt}" if status == "completed" else "",
                    size or None, err, stamp, stamp,
                ),
            )
        conn.commit()


def _grab(widget, name: str) -> None:
    from PyQt6.QtWidgets import QApplication

    QApplication.processEvents()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    widget.grab().save(str(path))
    print(f"  저장: {path.relative_to(_ROOT)}")


def main() -> int:
    from bootstrap import build_app_graph
    from bootstrap.runtime import create_qt_app, install_qt_message_filter, suppress_av_log
    from infrastructure.persistence.database import Database

    suppress_av_log()
    install_qt_message_filter()
    app = create_qt_app(sys.argv)

    # 경로는 전부 _SANDBOX 안이다(OVC_DATA_DIR) — 기본값을 그대로 쓴다.
    db = Database()
    db.initialize()
    _seed(db)
    graph = build_app_graph(db)

    from gui.main_window import MainWindow

    window = MainWindow(
        graph.view_models,
        stats_handler=graph.handlers.library.stats,
        auth_service=graph.services.auth_service,
        yt_oauth=graph.services.youtube_oauth,
        cleanup_fns=graph.handlers.library.cleanup_fns,
        db_backup=graph.services.db_backup,
    )
    window.resize(*WINDOW_SIZE)
    window.show()
    app.processEvents()

    pages = [
        (0, "library",  "라이브러리"),
        (1, "download", "다운로드"),
        (2, "monitor",  "채널 모니터링"),
        (3, "stats",    "통계"),
        (4, "settings", "설정"),
    ]
    print("화면 갈무리를 만듭니다…")
    for index, name, label in pages:
        window._stack.setCurrentIndex(index)
        for _ in range(8):     # 지연 조회·테마 적용이 자리 잡을 시간을 준다
            app.processEvents()
        print(f"- {label}")
        _grab(window, name)

    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
