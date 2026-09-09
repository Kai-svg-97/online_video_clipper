"""조립 루트(composition root) — 객체 그래프를 만드는 곳.

## 왜 패키지로 뺐나

예전에는 `main()` 하나가 609줄이었고 그 안에서 핸들러를 91번 생성했다. 기능을
추가하면 반드시 이 함수를 고쳐야 했고, 최근 6개월에 **39번** 고쳐졌다(변경 빈도
4위). 조립 순서 제약(DB 열기 전 스냅샷 부트스트랩, YouTube 인증 lazy binding)은
주석으로만 표현돼 있어 줄을 옮기면 조용히 깨졌다. main.py를 겨냥한 테스트는 OAuth
조립 헬퍼와 종료 tail 배치 줄뿐이어서(넷), **조립 자체에는 안전망이 없었다**.

지금은 컨텍스트별 파일로 갈라져 서로 부딪히지 않고, 의존 관계가 함수 인자로
드러나며(`bootstrap/handlers/__init__.py` 참조), `build_app_graph(db)` 하나만
불러 보면 조립이 성립하는지 테스트로 확인할 수 있다
(`tests/integration/test_composition_root.py`).

## 임포트는 여전히 지연된다

이 패키지의 모듈들은 인프라·GUI를 **모듈 수준에서** 임포트한다. 무겁지만, `main()`이
**스플래시를 띄운 뒤에** 이 패키지를 임포트하므로 시작 체감 성능은 예전과 같다
(예전에도 같은 임포트를 함수 안에서 했다). 그래서 **`main.py` 상단에서 이 패키지를
임포트하면 안 된다.**
"""

from __future__ import annotations

import logging

from bootstrap.context import AppGraph
from bootstrap.handlers import build_handlers
from bootstrap.persistence import bootstrap_cloud_snapshot, build_repositories, open_database
from bootstrap.services import build_services
from bootstrap.view_models import build_view_models

logger = logging.getLogger(__name__)


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
    )


__all__ = [
    "AppGraph",
    "bootstrap_cloud_snapshot",
    "build_app_graph",
    "open_database",
]
