"""뷰모델 묶음 — GUI가 한 번에 받아 쓰는 단위.

## 왜 여기(gui/)에 있나

`bootstrap/`(조립 루트)이 아니라 `gui/`가 이 정의를 소유한다. 조립 루트는 모든
레이어를 의존해도 되지만 그 반대는 안 된다 — `gui/main_window.py`가
`bootstrap.context`를 임포트하면 GUI가 조립 루트에 묶여 레이어 방향이 뒤집힌다.
"어떤 뷰모델들이 한 화면 묶음을 이루는가"는 프레젠테이션 계층의 관심사이므로
여기 두고, `bootstrap`이 이걸 채워 넣는다.

## 왜 묶음인가

`MainWindow`는 뷰모델을 낱개로 13개, `LibraryPanel`은 10개를 받았고 절반이 타입
힌트 없는 `song_vm=None` 꼴이었다. 뷰모델을 하나 추가하려면 조립부·`MainWindow`·
`LibraryPanel` 세 곳의 시그니처를 함께 고쳐야 했고, 한 곳을 잊으면 그 기능이
화면에서 조용히 죽었다(예외도 나지 않는다 — 그냥 `None`이라 비활성된다).

`LibraryPanel`은 **묶음을 받지 않는다.** 테스트가 `LibraryPanel(vm=library_vm)`
처럼 필요한 것만 넣어 최소 구성으로 만드는데, 그건 지켜야 할 성질이다(전체 묶음을
요구하면 테스트마다 쓰지도 않는 뷰모델 10개를 만들어야 한다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ViewModels:
    """한 애플리케이션 인스턴스의 뷰모델 전체.

    `frozen`인 이유는 조립이 시작할 때 한 번 일어나고 그 뒤로는 읽기만 하기
    때문이다 — 실행 중에 뷰모델을 바꿔 끼우는 경로는 없다.

    타입을 `Any`로 둔 것은 이 모듈이 뷰모델 11개를 임포트하면 `gui.view_models`
    안에서 순환 임포트가 생기기 때문이다(각 뷰모델이 `base`를 임포트하고 `base`가
    있는 같은 패키지다). 필드 **이름**이 계약이고, 실제 형은 조립부
    (`bootstrap/view_models.py`)가 임포트해 채운다.
    """

    library: Any
    download: Any
    clip: Any
    monitoring: Any
    playlist: Any
    feed: Any
    recommend: Any
    album: Any
    song: Any
    sync: Any
    transfer: Any
