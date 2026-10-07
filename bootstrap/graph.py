"""그래프 조립 본체 — `build_app_graph(db)`.

이 모듈은 인프라·GUI를 끌어오는 무거운 임포트를 모듈 수준에서 한다. `bootstrap/__init__`의
지연 `__getattr__`가 **처음 접근할 때만** 불러오므로, 스플래시 전에는 로드되지 않는다.
"""

from __future__ import annotations

from bootstrap.context import AppGraph
from bootstrap.handlers import build_handlers
from bootstrap.persistence import build_repositories
from bootstrap.services import build_services
from bootstrap.view_models import build_media_services, build_view_models


def build_app_graph(db) -> AppGraph:
    """열린 DB 위에 리포지토리·서비스·핸들러·뷰모델을 조립한다.

    `db`를 **인자로 받는다** — 테스트가 임시 DB를 넣어 그래프 전체를 만들어 볼 수
    있어야 하기 때문이다. DB를 여는 일과 그 위에 조립하는 일을 나눠 두면 조립만
    따로 검증할 수 있다.

    클라우드 스냅샷 부트스트랩은 **DB를 열기 전에** 일어나야 하므로 여기 포함되지
    않는다(`bootstrap_cloud_snapshot()`을 `open_database()` 앞에서 부른다).
    """
    services = build_services(db)
    repositories = build_repositories(db, services.sync_service)
    handlers = build_handlers(repositories, services)
    view_models = build_view_models(handlers, services)
    return AppGraph(
        repositories=repositories,
        services=services,
        handlers=handlers,
        view_models=view_models,
        media=build_media_services(services),
    )
