"""`Message`(키+파라미터) → 사람이 읽는 문장.

도메인이 돌려준 `Message`를 여기서 문장으로 만든다. 템플릿 표 하나가 곧 번역 단위다.

## `render()`는 절대 예외를 내지 않는다

업데이트 배지가 이 결과를 **`paintEvent` 경로에서** 쓴다. 거기서 난 파이썬 예외는
PyQt가 **프로세스 종료**로 처리한다(Windows 0xC0000409) — 로그도 예외 메시지도 남지
않고 앱이 그냥 사라진다. `CLAUDE.md`의 "델리게이트 `paint()` 안에서 예외를 내지
않는다"와 같은 부류다.

그래서 템플릿이 없거나 파라미터가 모자라도 **예외 대신 읽을 수 있는 무언가**를
돌려준다. 빈 화면이 죽은 앱보다 낫다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from domain.shared.messages import Message
from gui.text import _
from gui.text.formats import ByteUnit, format_bytes

logger = logging.getLogger(__name__)

# 키 → 문장. **키 하나가 완성된 문장 하나를 고른다** — 조각을 이어 붙이지 않는다.
# 덩어리 C3~C6에서 채워진다.
_TEMPLATES: dict[str, str] = {
    # ── 복합 필터 요약 ────────────────────────────────────────────
    # 프리셋 조각은 라벨 표(`labels.FILTER_PRESET_LABELS`)와 같은 말이지만 **키가
    # 다르다** — 저쪽은 콤보박스 항목, 이쪽은 "무엇으로 좁혔는지" 요약이다. 영어로
    # 가면 갈릴 수 있어(고르는 말 vs 걸린 상태) 처음부터 나눠 둔다.
    "filter.date.7d": "최근 1주",
    "filter.date.30d": "최근 1개월",
    "filter.date.90d": "최근 3개월",
    "filter.date.365d": "최근 1년",
    "filter.duration.short": "4분 미만",
    "filter.duration.medium": "4~20분",
    "filter.duration.long": "20분 이상",
    "filter.download.yes": "받아 둔 것만",
    "filter.download.no": "안 받은 것만",
    "filter.watched.yes": "본 것만",
    "filter.watched.no": "안 본 것만",
    "filter.channel": "채널 '{name}'",
    "filter.favorite": "즐겨찾기",

    # ── 음성 인식 예상 소요 ───────────────────────────────────────
    "transcribe.under_a_minute": "1분 미만",
    "transcribe.about_minutes": "약 {minutes}분",
    "transcribe.about_hours": "약 {hours}시간 {minutes}분",

    # ── 받는 시간대 ───────────────────────────────────────────────
    "schedule.always": "언제든 받습니다",
    "schedule.all_day": "하루 종일 받습니다",
    "schedule.window": "{start:02d}:00 ~ {end:02d}:00 에만 받습니다",
    "schedule.window_crossing": "{start:02d}:00 ~ {end:02d}:00 (다음 날) 에만 받습니다",

    # ── 구독 채널 새 영상 알림 ────────────────────────────────────
    "watch.count_only": "새 영상 {total}개",
    "watch.titles": "{titles}",
    "watch.titles_and_rest": "{titles}\n… 외 {rest}개",

    # ── 자동 업데이트 배지 ────────────────────────────────────────
    # 크기를 아는지·이유를 아는지에 따라 **키가 갈린다**. " (179.4MB)" 같은 조각을
    # 문장에 끼워 넣으면 언어가 바뀔 때 꽂을 자리가 없다.
    "update.badge.found": "⭳ v{version}",
    "update.found_tooltip": "현재 v{current} → v{new} 으로 업데이트됩니다\n눌러서 내려받기",
    "update.found_tooltip_sized":
        "현재 v{current} → v{new} 으로 업데이트됩니다 ({size_bytes})\n눌러서 내려받기",
    "update.badge.downloading_size": "v{version} · {downloaded_bytes}",
    "update.badge.downloading_pct": "v{version} · {percent}%",
    "update.downloading_unknown": "내려받는 중… {downloaded_bytes}",
    "update.downloading": "내려받는 중… {downloaded_bytes} / {total_bytes}",
    "update.badge.ready": "✓ v{version} 설치",
    "update.ready_tooltip": "v{new} 설치를 시작합니다\n앱이 닫히고 자동으로 다시 시작됩니다",
    "update.badge.installing": "설치 중…",
    "update.installing_tooltip": "잠시 후 자동으로 다시 시작됩니다",
    "update.badge.failed": "⟳ v{version}",
    "update.failed_tooltip": "내려받지 못했습니다: {reason}\n눌러서 다시 시도",
    "update.failed_tooltip_unknown": "내려받지 못했습니다: 알 수 없는 오류\n눌러서 다시 시도",

    # ── 원본 확인 결과의 자세한 사유 ──────────────────────────────
    "availability.removed": "원본이 삭제되었거나 주소가 바뀌었습니다",
    "availability.private": "비공개로 바뀌어 볼 수 없습니다",
    "availability.http_code": "응답 코드 {code}",
}

# 여러 조각을 한 줄로 이을 때 쓰는 구분자. 구분자도 언어 설정이라 여기 둔다.
JOIN_SEPARATOR = " · "


def _prepare(params: dict[str, object]) -> dict[str, object]:
    """파라미터 이름의 **접미사가 포맷을 고른다**.

    도메인이 "179.4MB" 같은 문자열을 만들지 않게 하는 장치다 — 바이트 수만 넘기면
    단위 표기는 여기서 붙는다(단위 표기도 언어 설정이다).
    """
    out = dict(params)
    for name, value in params.items():
        if name.endswith("_bytes") and isinstance(value, (int, float)):
            out[name] = format_bytes(value, unit=ByteUnit.MB)
    return out


def render(msg: Message | None) -> str:
    """문장 하나를 만든다. 실패해도 예외를 내지 않는다(모듈 설명 참조)."""
    if msg is None:
        return ""
    template = _TEMPLATES.get(msg.key)
    if template is None:
        logger.warning("표시 문구 템플릿이 없다: %s", msg.key)
        return msg.key
    try:
        return _(template).format(**_prepare(msg.as_dict()))
    except (KeyError, IndexError, ValueError):
        # 파라미터가 모자라거나 형식이 안 맞는다. 채우지 못한 원문이라도 돌려준다.
        logger.exception("표시 문구를 채우지 못했다: %s", msg.key)
        return _(template)


def render_all(msgs: Sequence[Message], sep: str = JOIN_SEPARATOR) -> str:
    """여러 조각을 한 줄로 잇는다(필터 요약 등)."""
    return sep.join(render(m) for m in msgs)
