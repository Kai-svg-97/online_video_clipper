"""상세 화면·플레이어가 쓰는 인프라 기능 묶음 — 조립 루트가 채운다.

## 왜 있나

`gui/`는 `infrastructure/`를 임포트하지 않는다(`tests/unit/
test_gui_does_not_import_infrastructure.py`가 강제). 예전에는 플레이어가 중계·자막
모듈을, 상세 화면이 Gemini 추출기를 함수 안에서 직접 불러왔다. 지금은 포트
(`domain/shared/ports.py`)만 알고, 구체 구현은 `bootstrap/view_models.py`의
`build_media_services()`가 넣어 `MainWindow → LibraryPanel/DownloadPanel →
VideoDetailWidget → InlinePlayer`로 생성자를 따라 내려간다.

낱개 인자 넷을 세 단계로 흘리면 한 곳을 잊을 때 그 기능만 조용히 죽는다 — 그래서
`ViewModels`처럼 묶음 하나로 넘긴다. 이 정의를 `gui/`가 갖는 이유도 같다
(`gui/view_models/bundle.py` 머리말).

## 비어 있으면

필드가 `None`이면 그 기능만 빠진다 — 요약 ⟳ 버튼이 숨고, 자막 목록을 조회하지
않고, 고화질은 실시간 remux 대신 병합 방식으로 받는다. 테스트가 위젯을 최소
구성으로 만들 수 있게 하려는 것이고, 앱에서는 조립 루트가 전부 채운다.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.shared.ports import ISummarySource, IStreamRelay, IVideoSubtitleSource

# 요약 추출기가 아는 언어를 모를 때의 기본값 — 이 앱의 원문 언어.
DEFAULT_SUMMARY_LANGUAGES: tuple[str, ...] = ("ko",)


@dataclass(frozen=True, slots=True)
class MediaServices:
    summary_source: ISummarySource | None = None
    # 요약 추출기가 만들 수 있는 언어 — ⟳ 가 앱 언어로 만들지, 한국어로 떨어질지 가른다.
    summary_languages: tuple[str, ...] = DEFAULT_SUMMARY_LANGUAGES
    stream_relay: IStreamRelay | None = None
    subtitles: IVideoSubtitleSource | None = None
