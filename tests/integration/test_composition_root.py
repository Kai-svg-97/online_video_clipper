"""조립 루트(`bootstrap/`) 스모크 테스트.

## 왜 이 테스트가 필요한가

조립은 예전에 `main()` 안에만 있었다 — 609줄, 핸들러 생성 91번. main.py를 겨냥한
테스트가 넷 있었지만(OAuth 조립 헬퍼 셋 + 종료 tail 배치 줄 하나) **조립 자체는
아무것도 확인하지 않았다.** 그런데 `main.py`는 최근 6개월에 39번 바뀌었다(변경 빈도
4위). 배선을 하나 빠뜨렸는지는 앱을 직접 띄워 그 기능을 눌러 봐야 알 수 있었고,
빠뜨린 경우 예외도 나지 않는다 — 그냥 `None`이라 그 기능이 조용히 비활성된다.

여기서 지키는 계약:

* 그래프 전체가 예외 없이 조립된다(핸들러 인자 이름·개수가 맞다).
* 모든 뷰모델이 만들어진다 — `None`으로 조용히 빠지지 않는다.
* 워커를 띄우는 뷰모델은 `shutdown()`을 갖는다(종료 시 QThread 파괴 방지).
* 조립은 **네트워크를 쓰지 않는다** — 시작할 때 외부를 때리면 오프라인에서 앱이
  안 뜬다.
* YouTube 인증은 **조립 시점에 해석되지 않는다**(lazy binding). 시작 시 keyring
  접근 200~300ms를 미루는 최적화가 살아 있는지 확인한다.

DB는 임시 파일이라 실사용 라이브러리를 건드리지 않는다.
"""

from __future__ import annotations

import dataclasses

import pytest

from infrastructure.persistence.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "composition.db")
    d.initialize()
    return d


@pytest.fixture
def graph(db, qapp_instance):
    """뷰모델이 QObject라 QApplication이 필요하다."""
    from bootstrap import build_app_graph

    g = build_app_graph(db)
    yield g
    # 조립만 했으니 워커는 없지만, 실패 시 남는 스레드가 다음 테스트를 오염시키지
    # 않게 정리한다. `astuple`은 값을 깊은 복사해서 QObject에서 터지므로
    # `fields` + `getattr`로 원본을 그대로 훑는다.
    for f in dataclasses.fields(g.view_models):
        shutdown = getattr(getattr(g.view_models, f.name), "shutdown", None)
        if callable(shutdown):
            shutdown()


@pytest.fixture(scope="session")
def qapp_instance():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


class TestGraphBuilds:
    def test_builds_without_error(self, graph):
        assert graph.repositories is not None
        assert graph.services is not None
        assert graph.handlers is not None
        assert graph.view_models is not None

    def test_every_repository_present(self, graph):
        for f in dataclasses.fields(graph.repositories):
            assert getattr(graph.repositories, f.name) is not None, (
                f"리포지토리 {f.name}이 조립되지 않았다"
            )

    def test_every_view_model_present(self, graph):
        for f in dataclasses.fields(graph.view_models):
            assert getattr(graph.view_models, f.name) is not None, (
                f"뷰모델 {f.name}이 조립되지 않았다 — 화면에서 그 기능이 조용히 죽는다"
            )

    def test_every_handler_group_fully_wired(self, graph):
        """핸들러 묶음의 모든 필드가 채워졌는지 — 빈 칸은 런타임 AttributeError가 된다."""
        missing: list[str] = []
        for group_field in dataclasses.fields(graph.handlers):
            group = getattr(graph.handlers, group_field.name)
            for f in dataclasses.fields(group):
                if getattr(group, f.name) is None:
                    missing.append(f"{group_field.name}.{f.name}")
        assert not missing, f"조립되지 않은 핸들러: {missing}"


class TestWorkerLifecycleContract:
    """조립된 실제 뷰모델이 종료 규약을 만족하는가.

    `tests/gui/test_vm_worker_contract.py`는 소스를 AST로 보지만, 여기서는
    **실제로 만들어진 객체**가 `shutdown()`을 갖는지 본다(믹스인 상속이 런타임에
    실제로 먹었는지까지 확인된다).
    """

    def test_all_view_models_shut_down(self, graph):
        for f in dataclasses.fields(graph.view_models):
            vm = getattr(graph.view_models, f.name)
            assert callable(getattr(vm, "shutdown", None)), (
                f"{f.name} 뷰모델에 shutdown()이 없다 — 앱 종료 시 실행 중 QThread가 "
                "파괴되며 프로세스가 죽는다"
            )


class TestLazyYouTubeAuth:
    """시작 시 keyring을 건드리지 않는다(Phase 2 성능 최적화 보존)."""

    def test_youtube_api_is_a_callback_not_an_adapter(self, graph):
        provider = graph.services.youtube_api
        assert callable(provider), (
            "Services.youtube_api는 어댑터가 아니라 콜백이어야 한다 — 조립 시점에 "
            "인증을 해석하면 시작이 200~300ms 느려진다"
        )

    def test_credentials_not_read_during_build(self, db, qapp_instance, monkeypatch):
        """조립 중에는 `get_credentials()`가 불리지 않는다."""
        from bootstrap import build_app_graph
        from infrastructure.youtube import oauth_adapter

        calls: list[int] = []
        monkeypatch.setattr(
            oauth_adapter.YouTubeOAuthAdapter,
            "get_credentials",
            lambda self: calls.append(1),
        )
        graph = build_app_graph(db)
        assert calls == [], "조립 중에 YouTube 인증이 해석됐다(lazy binding 회귀)"

        # 콜백을 실제로 부르면 그때 해석된다 — 그리고 결과는 캐시된다.
        graph.services.youtube_api()
        graph.services.youtube_api()
        assert len(calls) == 1, "인증 해석 결과가 캐시되지 않는다(keyring 반복 접근)"


@pytest.fixture
def isolated_theme_manager():
    """싱글턴 `ThemeManager`를 일회용 인스턴스로 갈아 끼운다.

    `LibraryPanel`은 `ThemeManager.instance().theme_changed`에 **위젯을 캡처한
    람다**를 연결한다(알려진 누수 — `docs/architecture/design-decisions.md`의
    "미해결: ThemeManager 싱글턴 람다 연결" 참고. 바운드 메서드로 바꾸면 패널
    파괴 시 프로세스가 죽어 고치지 못한 상태다).

    아래 테스트는 창을 만들고 **버리므로**, 그 람다가 진짜 싱글턴에 남으면 나중에
    도는 테마 테스트가 죽은 `_PlaylistTree`를 건드려 터진다 — 이 테스트와 무관한
    곳에서 실패가 나타난다. `tests/gui/test_theme_transition.py`가 같은 이유로 쓰는
    우회를 그대로 적용해, 누수를 일회용 인스턴스에 가둔 뒤 함께 버린다.
    """
    from gui.themes.manager import ThemeManager

    saved = ThemeManager._instance
    ThemeManager._instance = None
    ThemeManager.instance()          # 이 테스트 동안 쓰일 일회용 인스턴스
    try:
        yield
    finally:
        ThemeManager._instance = saved


class TestMainWindowWiring:
    """조립된 그래프로 실제 메인 창이 만들어지는가.

    그래프가 성립하는 것과 **화면이 그걸 받아 쓰는 것**은 다르다. `MainWindow`는
    뷰모델을 묶음 하나로 받고 그걸 `LibraryPanel`·`DownloadPanel`·`SettingsPanel`
    등에 낱개로 풀어 넘기는데, 필드 이름이 하나 어긋나면 앱을 띄워 그 패널을 열어
    봐야 알 수 있다(예외도 안 나고 그냥 그 기능이 비활성된다).

    창을 `show()`하지 않으므로 데스크톱에 뜨지 않고, DB는 임시 파일이다.
    """

    def test_main_window_constructs_from_graph(
        self, graph, qapp_instance, isolated_theme_manager
    ):
        from gui.main_window import MainWindow

        window = MainWindow(
            graph.view_models,
            stats_handler=graph.handlers.library.stats,
            auth_service=graph.services.auth_service,
            yt_oauth=graph.services.youtube_oauth,
            cleanup_fns=graph.handlers.library.cleanup_fns,
        )
        try:
            # 사이드바가 가리키는 페이지가 전부 만들어졌는지 — 하나라도 빠지면
            # 그 메뉴를 눌렀을 때 빈 화면이 된다.
            assert window._stack.count() >= 5, (
                f"패널 스택이 {window._stack.count()}개뿐이다 — "
                "라이브러리·다운로드·모니터링·통계·설정 5개가 있어야 한다"
            )
            assert window._library_vm is graph.view_models.library
            assert window._song_vm is graph.view_models.song
            assert window._transfer_vm is graph.view_models.transfer
        finally:
            window.close()

    def test_close_event_shuts_down_every_view_model(
        self, graph, qapp_instance, isolated_theme_manager
    ):
        """`closeEvent`가 **모든** 뷰모델을 정리하는가 — 목록 누락 재발 방지.

        예전 `closeEvent`에는 뷰모델이 손으로 나열돼 있었고 clip·monitoring·playlist
        셋이 빠져 있었다. 지금은 `shutdown_all`이 발견하므로, 뷰모델을 추가해도
        자동으로 포함된다.
        """
        from gui.main_window import MainWindow
        from PyQt6.QtGui import QCloseEvent

        window = MainWindow(
            graph.view_models,
            stats_handler=graph.handlers.library.stats,
            auth_service=graph.services.auth_service,
            yt_oauth=graph.services.youtube_oauth,
            cleanup_fns=graph.handlers.library.cleanup_fns,
        )
        called: set[str] = set()
        for f in dataclasses.fields(graph.view_models):
            vm = getattr(graph.view_models, f.name)
            vm.shutdown = (lambda name=f.name: called.add(name))  # type: ignore[method-assign]

        window.closeEvent(QCloseEvent())

        expected = {f.name for f in dataclasses.fields(graph.view_models)}
        assert called == expected, f"정리되지 않은 뷰모델: {sorted(expected - called)}"


class TestNoNetworkAtBuild:
    """조립은 외부를 때리지 않는다 — 오프라인에서도 앱이 떠야 한다."""

    def test_build_makes_no_http_request(self, db, qapp_instance, monkeypatch):
        import requests

        def _boom(*_a, **_kw):
            raise AssertionError("조립 중 네트워크 요청이 발생했다")

        monkeypatch.setattr(requests.Session, "request", _boom)
        monkeypatch.setattr(requests, "request", _boom, raising=False)

        from bootstrap import build_app_graph

        build_app_graph(db)
