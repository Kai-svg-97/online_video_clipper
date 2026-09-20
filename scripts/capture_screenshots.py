"""상세 설명서에 넣을 화면 갈무리를 만든다 — `docs/manual/images/*.png`.

**왜 스크립트인가**: 손으로 찍은 갈무리는 화면이 바뀌면 조용히 낡는다. 여기서는
임시 DB에 표본 자료를 심고 실제 앱 화면을 그려 저장하므로, UI가 바뀌면 다시 돌리기만
하면 된다. 사용자의 실제 라이브러리는 **건드리지도, 찍히지도 않는다** — `Database`에
임시 경로를 직접 넘긴다.

사용:
    python scripts/capture_screenshots.py

주의: `QWidget.grab()`은 창을 화면에 띄우지 않고도 그려 낸다. 창을 실제로 띄우면
    테마·애니메이션이 자리 잡기 전에 찍힐 수 있어 오히려 결과가 불안정하다.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

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

    tmp = Path(tempfile.mkdtemp(prefix="ovc_shots_"))
    db = Database(tmp / "library.db")
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
