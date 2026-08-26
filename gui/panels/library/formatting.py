"""표시용 포맷·색 파생·드롭 MIME 해석 — 위젯이 아닌 순수 함수 모음.

화면 어디서나 쓰는 작은 규칙들이라 한곳에 모았다. 특히 `tag_color`는 프로세스마다
색이 달라지지 않도록 `zlib.crc32`를 쓰고(파이썬 `hash`는 실행마다 무작위화된다),
`_url_from_mime`은 브라우저마다 다른 URL MIME 형식을 흡수한다.
"""

from __future__ import annotations

import logging
import zlib

from PyQt6.QtCore import (
    QMimeData,
)

from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

from gui.panels.library.constants import _TAG_PALETTE

logger = logging.getLogger(__name__)


def _t() -> ThemeTokens:
    """현재 테마 토큰을 반환하는 단축 함수."""
    return ThemeManager.instance().current()


def _fmt_elapsed(iso: str | None) -> str:
    """ISO 시간 문자열을 '3일 전' 형식으로 변환한다."""
    if not iso:
        return ""
    try:
        from datetime import datetime, timezone  # noqa: PLC0415
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        s = diff.total_seconds()
        if s < 60:
            return "방금"
        if s < 3600:
            return f"{int(s // 60)}분 전"
        if s < 86400:
            return f"{int(s // 3600)}시간 전"
        if s < 86400 * 30:
            return f"{int(s // 86400)}일 전"
        if s < 86400 * 365:
            return f"{int(s // (86400 * 30))}개월 전"
        return f"{int(s // (86400 * 365))}년 전"
    except Exception:
        logger.exception("경과 시간 포맷 변환 실패")
        return ""


def tag_color(name: str) -> str:
    """태그·카테고리 이름에서 표시 색상을 결정한다.

    `hash()`는 파이썬 str 해시가 PYTHONHASHSEED로 프로세스마다 무작위화되어
    앱을 다시 켤 때마다 색이 바뀌었다. crc32는 시드에 의존하지 않아
    실행·플랫폼에 걸쳐 항상 같은 색을 준다.
    """
    digest = zlib.crc32(name.encode("utf-8"))
    return _TAG_PALETTE[digest % len(_TAG_PALETTE)]


def _mix(fg: str, bg: str, ratio: float) -> str:
    """두 색을 비율로 섞는다(칩 테두리처럼 '토큰 사이' 값이 필요한 자리용).

    토큰을 새로 만들지 않는 이유는 값이 기존 토큰에서 기계적으로 나오기 때문이다 —
    프리셋마다 손으로 적으면 원본 토큰을 바꿀 때 같이 고치는 것을 잊는다.
    """
    f, b = (c.lstrip("#") for c in (fg, bg))
    parts = (
        round(int(f[i : i + 2], 16) * ratio + int(b[i : i + 2], 16) * (1 - ratio))
        for i in (0, 2, 4)
    )
    return "#" + "".join(f"{p:02x}" for p in parts)


def chip_colors(tokens, selected: bool, data_color: str | None = None) -> dict[str, str]:
    """칩(인기 태그 버튼·태그 리스트 항목)의 색상을 테마 토큰에서 파생한다.

    미선택은 카드 표면(bg_elevated) + 테두리로 배경에서 떠 보이게 하고,
    선택은 accent(또는 태그 고유 색)로 채운다.

    **테두리를 `border_muted`로 두면 칩에 경계가 없다.** 칩 채움색은 배경 바
    대비가 11개 테마에서 1.05~1.19:1뿐이라 채움만으로는 절대 구분되지 않는데,
    `border_muted`도 채움 대비 1.20~1.68:1이어서 전 테마가 WCAG 1.4.11(3:1)에
    미달했다(실측 — 다크 테마에서 칩이 사라지고 카운트 배지만 떠 보였다).
    `text_muted`를 채움 쪽으로 80% 섞어 3.37~4.24:1을 확보한다.
    """
    if selected:
        return {
            "bg": data_color or tokens.accent,
            "border": data_color or tokens.accent,
            "text": tokens.text_on_accent,
            "badge_bg": tokens.bg_overlay,
            "badge_text": tokens.text_primary,
        }
    return {
        "bg": tokens.bg_elevated,
        "border": _mix(tokens.text_muted, tokens.bg_elevated, 0.8),
        "text": tokens.text_secondary,
        "badge_bg": tokens.bg_overlay,
        "badge_text": tokens.text_secondary,
    }


def _url_from_mime(mime: QMimeData) -> str:
    """MIME 데이터에서 http/https URL을 추출한다.

    Windows에서 브라우저 URL 드래그 시 dropEvent 시점에 데이터가 채워지므로
    dragEnterEvent에서는 데이터가 비어있을 수 있다.
    여러 MIME 포맷(text/plain, text/uri-list, text/x-moz-url)을 순서대로 확인한다.
    """
    # 1. text/plain
    text = mime.text().strip()
    if text.startswith(("http://", "https://")):
        return text
    # 2. Qt URL 목록 (text/uri-list 파싱 결과)
    if mime.hasUrls():
        for qu in mime.urls():
            s = qu.toString().strip()
            if s.startswith(("http://", "https://")):
                return s
    # 3. text/uri-list 직접 읽기 (hasUrls()가 False인 경우 대비)
    #    + Windows 네이티브 URL 포맷(브라우저에서 끌 때 이것만 실려 오는 경우가 있다).
    #    …LocatorW는 UTF-16LE라 utf-8로 읽으면 NUL이 섞여 앞부분만 잘린다.
    for fmt, encoding in (
        ("text/uri-list", "utf-8"),
        ("text/x-moz-url", "utf-16-le"),
        ('application/x-qt-windows-mime;value="UniformResourceLocatorW"', "utf-16-le"),
        ('application/x-qt-windows-mime;value="UniformResourceLocator"', "utf-8"),
    ):
        if mime.hasFormat(fmt):
            try:
                raw = bytes(mime.data(fmt)).decode(encoding, errors="ignore")
                for line in raw.replace("\x00", "\n").splitlines():
                    line = line.strip()
                    if line.startswith(("http://", "https://")):
                        return line
            except Exception:
                logger.exception("MIME 데이터에서 URL 추출 실패")
    return ""


def _mime_may_contain_url(mime: QMimeData) -> bool:
    """dragEnterEvent 시점에 URL 드래그 여부를 판단한다.

    Windows에서 브라우저 드래그 시 dragEnter 단계에서 MIME 내용이 아직
    채워지지 않을 수 있다. 데이터 내용이 아닌 포맷 존재 여부만 확인한다.
    """
    if _url_from_mime(mime):
        return True
    # 포맷 존재만 확인 (내용은 dropEvent에서 검증).
    # text/plain과 Windows 네이티브 URL 포맷까지 본다 — 브라우저·사이트에 따라
    # dragEnter 시점에 uri-list가 없고 텍스트만 실려 오는 경우가 있어, 이 목록이
    # 좁으면 트리 위에서 드래그 자체가 거부돼 드롭이 조용히 죽는다.
    return mime.hasUrls() or any(
        mime.hasFormat(f) for f in (
            "text/uri-list",
            "text/x-moz-url",
            "text/plain",
            'application/x-qt-windows-mime;value="UniformResourceLocator"',
            'application/x-qt-windows-mime;value="UniformResourceLocatorW"',
        )
    )


def _relative_time(date_str: str | None) -> str:
    """Return a Korean relative time string like '3년 전' from an ISO date string."""
    if not date_str:
        return ""
    from datetime import date, datetime
    try:
        if len(date_str) == 8 and date_str.isdigit():        # YYYYMMDD (yt-dlp)
            pub = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
        elif "T" in date_str or " " in date_str:
            pub = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        else:
            pub = date.fromisoformat(date_str)
        today = date.today()
        days = (today - pub).days
        if days < 0:
            return ""
        if days < 7:
            return f"{days}일 전" if days > 0 else "오늘"
        if days < 30:
            return f"{days // 7}주 전"
        if days < 365:
            return f"{days // 30}개월 전"
        return f"{days // 365}년 전"
    except (ValueError, TypeError):
        return ""


def _pub_sort_key(date_str: str | None) -> int:
    """published_at(YYYYMMDD·ISO·date)을 정렬용 ordinal로 변환. 없거나 파싱 실패 시 0(맨 뒤)."""
    if not date_str:
        return 0
    from datetime import date, datetime
    try:
        if len(date_str) == 8 and date_str.isdigit():        # YYYYMMDD (yt-dlp)
            return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:])).toordinal()
        if "T" in date_str or " " in date_str:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date().toordinal()
        return date.fromisoformat(date_str).toordinal()
    except (ValueError, TypeError):
        return 0


def _fmt_views(view_count: int | None) -> str:
    """Return a short Korean view count string like '1.2만 회'."""
    if view_count is None:
        return ""
    if view_count < 1_000:
        return f"조회수 {view_count}회"
    if view_count < 10_000:
        return f"조회수 {view_count / 1000:.1f}천 회"
    if view_count < 100_000_000:
        return f"조회수 {view_count / 10000:.1f}만 회"
    return f"조회수 {view_count / 100_000_000:.1f}억 회"
