"""읽는 영역(요약·가사)의 글자 크기 조절.

요약과 가사는 **읽으라고 있는 글**인데 크기가 코드에 박혀 있었다. 화면·시력·거리에
따라 알맞은 크기가 다르므로 사용자가 직접 키우고 줄일 수 있어야 한다.

규칙
* 배율 하나를 두 영역이 공유한다 — "글자 크기"는 화면 설정이지 영역별 취향이 아니다.
* `Ctrl` + `+` / `-` 로 조절하고 `Ctrl+0`(또는 헤더의 배율 버튼)으로 기본값(100%)으로
  되돌린다. 단일 키는 플레이어 몫이므로 쓰지 않는다(프로젝트 입력 규칙).
* 값은 영상별이 아니라 **전역**이라 `config.yaml`에 저장한다(자막 크기와 같은 취급).

`scaled_pt`가 반올림과 하한을 한곳에서 책임진다 — 배율을 곱한 자리마다 따로 계산하면
영역마다 1pt씩 어긋난다.
"""

from __future__ import annotations

import logging

import config.settings as _settings

logger = logging.getLogger(__name__)

DEFAULT_SCALE = 1.0
MIN_SCALE = 0.7
MAX_SCALE = 2.5
STEP = 0.1
_SETTING_KEY = "detail_text_scale"
# 요약(QTextBrowser)의 기준 글자 크기 — 여기에 배율을 곱한다.
SUMMARY_BASE_PT = 10


def clamp_scale(value: float) -> float:
    """허용 범위로 자르고 소수 둘째 자리에서 끊는다.

    0.1을 거듭 더하면 `1.9700000000000002` 같은 값이 저장되므로(자막 배율에서 실제로
    겪었다) 여기서 잘라 둔다.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SCALE
    return round(min(MAX_SCALE, max(MIN_SCALE, v)), 2)


def scaled_pt(base_pt: float, scale: float) -> int:
    """기준 크기에 배율을 적용한 pt(최소 6pt — 그 아래는 읽을 수 없다)."""
    return max(6, round(base_pt * clamp_scale(scale)))


def load_scale() -> float:
    # 다른 설정과 같은 방식 — 모듈 변수를 읽는다(save_setting이 함께 갱신한다).
    return clamp_scale(getattr(_settings, "DETAIL_TEXT_SCALE", DEFAULT_SCALE))


def save_scale(scale: float) -> None:
    try:
        _settings.save_setting(_SETTING_KEY, clamp_scale(scale))
    except Exception:
        logger.exception("글자 크기 설정을 저장하지 못했습니다")


def scale_label(scale: float) -> str:
    """배율 버튼에 적을 문구 — 지금 몇 %인지 보여야 되돌릴 생각도 든다."""
    return f"{round(clamp_scale(scale) * 100)}%"


ZOOM_TOOLTIP = (
    "글자 크기 — 클릭하면 기본값(100%)으로 되돌립니다.\n"
    "Ctrl + '+' 확대 · Ctrl + '-' 축소 · Ctrl + 0 기본값"
)
