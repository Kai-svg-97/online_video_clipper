"""애플리케이션 진입점.

**여기에는 조립 목록이 아니라 순서만 있다.** 무엇을 어떻게 만드는지는
`bootstrap/` 패키지가 알고, 이 파일은 "무엇이 무엇보다 먼저여야 하는가"만 말한다.

예전에는 `main()` 하나가 609줄이었고 그 안에서 핸들러를 91번 생성했다. 기능을
추가하면 반드시 이 함수를 고쳐야 했고 최근 6개월에 39번 고쳐졌는데, 조립 순서
제약은 주석으로만 표현돼 있어 줄을 옮기면 조용히 깨졌다. 지금은 그 제약이 함수
호출 순서로 드러나고, 조립 자체는 테스트로 검증된다
(`tests/integration/test_composition_root.py`).

## 임포트를 미루는 것이 중요하다

상단 임포트는 **가벼운 것만** 둔다. 인프라·GUI를 끌어오는 `bootstrap` 패키지는
스플래시를 띄운 **뒤에** 임포트한다 — 그래야 사용자가 아이콘을 누른 직후 창을 본다
(프로젝트가 명시적으로 최적화한 항목이다). 이 순서를 바꾸면 시작이 눈에 띄게
느려진다.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main() -> int:
    # 1. Qt 로그 억제 — Qt를 쓰기 전에 걸어야 초기 메시지까지 잡힌다.
    from bootstrap.runtime import (
        create_qt_app,
        install_pending_update,
        install_qt_message_filter,
        show_splash,
        suppress_av_log,
    )

    suppress_av_log()
    install_qt_message_filter()

    # 2. QApplication → 스플래시. 무거운 초기화보다 앞에 있어야 창이 즉시 뜬다.
    app = create_qt_app(sys.argv)
    splash = show_splash(app)

    # 3. 데이터 디렉터리·로깅 — 아래 단계들이 로그를 남길 수 있어야 한다.
    from config.settings import ensure_data_dirs
    from utils.logging_config import setup_logging

    ensure_data_dirs()
    setup_logging()

    # 4. 중복 실행 가드 — **DB를 열기 전에** 판단한다. 업데이트 직후 인스톨러와
    #    배치가 겹쳐 실행되거나 사용자가 아이콘을 연달아 눌러도, 두 프로세스가 같은
    #    DB를 동시에 건드리는 일이 없어야 한다.
    from gui.single_instance import SingleInstanceGuard

    guard = SingleInstanceGuard()
    if not guard.try_acquire():
        logger.info("이미 실행 중인 인스턴스가 있어 종료한다")
        splash.close()
        return 0

    # 5. 여기서부터 무거운 임포트 — 스플래시가 보이는 동안 수행된다.
    from bootstrap import bootstrap_cloud_snapshot, build_app_graph, open_database

    # 6. 클라우드 스냅샷 부트스트랩은 **DB를 열기 전에**. 스냅샷 import가 DB 파일을
    #    통째로 교체하므로 열린 연결이 있으면 안 된다(신규 기기만 해당).
    bootstrap_cloud_snapshot()
    db = open_database()

    # 7. 객체 그래프 조립 — 리포지토리·서비스·핸들러·뷰모델.
    graph = build_app_graph(db)

    # 8. 메인 창. 뷰모델은 묶음 하나로 넘긴다(낱개 13개였다).
    from gui.main_window import MainWindow

    window = MainWindow(
        graph.view_models,
        stats_handler=graph.handlers.library.stats,
        auth_service=graph.services.auth_service,
        yt_oauth=graph.services.youtube_oauth,
        cleanup_fns=graph.handlers.library.cleanup_fns,
    )

    # 9. 자동 업데이트 컨트롤러 — 창이 있어야 배지·다이얼로그를 띄울 수 있다.
    from gui.updater.update_controller import UpdateController

    window.set_update_controller(
        UpdateController(graph.handlers.updater.check, graph.handlers.updater.download, window)
    )

    # 10. 스플래시 닫고 창 표시.
    splash.finish(window)
    window.show()

    # 두 번째 인스턴스가 실행되면 이 창을 앞으로 부른다(그쪽은 즉시 종료된다).
    guard.set_activate_callback(_make_activator(window))

    # 연결돼 있으면 기동 후 1회 + 주기 자동 동기화.
    graph.view_models.sync.start_auto_sync()

    exit_code = app.exec()
    guard.release()

    # 11. 앱이 완전히 종료된 뒤에만 업데이트를 설치한다(실행 중에는 파일이 잠긴다).
    install_pending_update()
    return exit_code


def _make_activator(window):
    """중복 실행 시 기존 창을 앞으로 부르는 콜백.

    창을 캡처한 클로저지만 `main()`이 살아 있는 동안만 쓰이고 창보다 오래 살지
    않으므로 안전하다(워커 슬롯에 람다를 쓰지 말라는 규칙은 QThread 신호 연결에
    대한 것이다 — 여기는 그 경로가 아니다).
    """

    def activate() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    return activate


if __name__ == "__main__":
    sys.exit(main())
