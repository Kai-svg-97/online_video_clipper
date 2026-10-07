"""조립 루트(composition root) — 객체 그래프를 만드는 곳.

## 왜 패키지로 뺐나

예전에는 `main()` 하나가 609줄이었고 그 안에서 핸들러를 91번 생성했다. 기능을
추가하면 반드시 이 함수를 고쳐야 했고, 최근 6개월에 **39번** 고쳐졌다(변경 빈도
4위). 조립 순서 제약(DB 열기 전 스냅샷 부트스트랩, YouTube 인증 lazy binding)은
주석으로만 표현돼 있어 줄을 옮기면 조용히 깨졌다. main.py를 겨냥한 테스트는 OAuth
조립 헬퍼와 종료 tail 배치 줄뿐이어서(넷), **조립 자체에는 안전망이 없었다**.

지금은 컨텍스트별 파일로 갈라져 서로 부딪히지 않고, 의존 관계가 함수 인자로
드러나며(`bootstrap/handlers/__init__.py` 참조), `build_app_graph(db)`(`bootstrap/graph.py`) 하나만
불러 보면 조립이 성립하는지 테스트로 확인할 수 있다
(`tests/integration/test_composition_root.py`).

## 임포트는 지연된다 (PEP 562)

조립 본체(`handlers`·`services`·`persistence`·`view_models`·`context`)는 인프라·GUI를
**모듈 수준에서** 임포트해 무겁다(웜 약 0.5초, 콜드 약 2초). 그래서 이 `__init__`은
아무것도 미리 임포트하지 않고, `build_app_graph` 등 공개 이름을 **처음 접근할 때**
모듈 수준 `__getattr__`가 해당 모듈을 임포트한다. `main()`이 `bootstrap.runtime`(가벼움)을
스플래시 전에 임포트해도 조립 본체가 딸려 오지 않는다. 지켜 주는 시험:
`tests/unit/test_main_startup_order.py`. 그래서 **이 파일에 무거운 모듈 수준 임포트를
추가하면 안 된다**(타입 힌트용은 `TYPE_CHECKING` 블록).
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bootstrap.context import AppGraph
    from bootstrap.graph import build_app_graph
    from bootstrap.persistence import bootstrap_cloud_snapshot, open_database

logger = logging.getLogger(__name__)

# 공개 이름 → 그것이 사는 서브모듈. 처음 접근할 때만 임포트한다.
_LAZY: dict[str, str] = {
    "AppGraph": "bootstrap.context",
    "build_app_graph": "bootstrap.graph",
    "bootstrap_cloud_snapshot": "bootstrap.persistence",
    "open_database": "bootstrap.persistence",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value   # 다음부터는 일반 속성 조회
    return value


__all__ = [
    "AppGraph",
    "bootstrap_cloud_snapshot",
    "build_app_graph",
    "open_database",
]
