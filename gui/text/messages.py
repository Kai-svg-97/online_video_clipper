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

from domain.shared.messages import DisplayError, Message
from gui.text import tr
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
    "availability.not_youtube": "YouTube 영상이 아닙니다",

    # ── 오류 사유 — 애플리케이션·인프라의 `DisplayError` ──────────────
    # 번역할 수 없는 원문(yt-dlp·네트워크가 준 영어 메시지)을 그대로 싣는 자리.
    "error.raw": "{reason}",

    # ── 등록 후 자동 보강(가사·요약) 결과 ────────────────────────────
    "enrich.video_not_found": "영상을 찾을 수 없습니다",
    "enrich.lyrics_exists": "가사가 이미 있습니다",
    "enrich.no_lyrics_fetcher": "가사 조회기가 설정되지 않았습니다",
    "enrich.lyrics_not_found": "가사를 찾지 못했습니다",
    "enrich.lyrics_lines": "{n}줄",
    "enrich.summary_exists": "요약이 이미 있습니다",
    "enrich.no_summary_source": "요약 추출기가 설정되지 않았습니다",
    "enrich.summary_no_button": "이 영상에는 '질문하기' 버튼이 없어 요약을 가져올 수 없습니다",
    "enrich.summary_needs_login": "YouTube 로그인이 필요합니다(설정에서 쿠키 등록)",
    "enrich.summary_failed": "요약을 가져오지 못했습니다",
    "enrich.summary_chars": "{n}자",

    # ── 라이브러리 가져오기 충돌 — 가사 미리보기 ─────────────────────
    "transfer.lyrics_preview": "{lines}줄 · {preview}",

    # ── 앨범 요약 조각(출처가 설명을 주지 않을 때) ───────────────────
    "album.released": "{date} 발매",
    "album.track_count": "{n}곡",
    "album.library_count": "내 라이브러리 {n}곡",

    # ── 포맷 변환 ─────────────────────────────────────────────────
    "convert.unknown_preset": "알 수 없는 변환 프리셋: {preset}",
    "convert.source_missing": "원본 파일이 없습니다: {path}",
    "convert.ffmpeg_failed": "ffmpeg 변환 실패 (코드 {code})",

    # ── 음성 인식 ─────────────────────────────────────────────────
    "transcribe.file_missing": "전사할 파일이 없습니다: {path}",

    # ── YouTube 재생목록 ──────────────────────────────────────────
    "playlist.api_credentials_unavailable": "YouTube API 자격증명을 가져올 수 없습니다.",
    "playlist.api_not_connected":
        "YouTube API가 연결되지 않았습니다.\n설정 > YouTube API 연동에서 인증하세요.",
    "playlist.import_failed":
        "재생목록을 가져올 수 없습니다.\n• yt-dlp: {ytdlp_error}\n• YouTube API: {api_error}",
    "playlist.private_needs_auth":
        "비공개 재생목록을 가져오려면 YouTube 계정 인증이 필요합니다.\n"
        "설정 > YouTube 계정에서 브라우저 프로필을 선택하거나\n"
        "쿠키 파일(.txt)을 등록해 주세요.",
    "media.browser_cookie_unreadable":
        "브라우저 쿠키를 읽을 수 없습니다.\n"
        "Chrome이 실행 중이면 종료 후 재시도하거나,\n"
        "설정 > YouTube 계정에서 쿠키 파일을 직접 등록하세요.",
    "media.cookie_decrypt_failed":
        "Chrome 쿠키를 복호화할 수 없습니다 (DPAPI 오류).\n"
        "다음 중 하나를 시도해 주세요:\n"
        "• Chrome을 완전히 종료한 후 다시 시도\n"
        "• 설정 > YouTube 계정에서 Firefox를 선택\n"
        "• 설정 > YouTube 계정에서 재로그인(Playwright 방식)",

    # ── 클라우드 동기화 ───────────────────────────────────────────
    "sync.schema_newer": "원격 변경이 더 최신 스키마를 요구합니다 — 앱 업데이트가 필요합니다.",
    "sync.snapshot_sha_mismatch":
        "스냅샷 sha256 불일치 — 손상/불완전 다운로드: {actual} != {expected}",
    "sync.snapshot_integrity_failed": "스냅샷 integrity_check 실패: {result}",
    "sync.snapshot_schema_newer": "원격 스냅샷이 더 최신 스키마 — 앱 업데이트 필요: {ids}",
    "sync.gdrive_auth_required": "Google Drive 인증 필요 — 먼저 연결하세요",
    "sync.onedrive_auth_required": "OneDrive 인증 필요 — 먼저 연결하세요",

    # ── YouTube OAuth 클라이언트 설정 ─────────────────────────────
    "oauth.client_config_missing": "YouTube OAuth 클라이언트 설정이 포함되지 않았습니다.",
    "oauth.config_unreadable": "OAuth 설정 JSON을 읽을 수 없습니다: {path}",
    "oauth.not_desktop_installed": "Desktop installed OAuth 설정이 아닙니다: {path}",
    "oauth.missing_field": "OAuth 설정 필드가 없습니다: {field} ({path})",
    "oauth.no_loopback_redirect": "localhost loopback redirect가 없습니다: {path}",

    # ── 업데이트 내려받기 실패 사유 ───────────────────────────────
    "update.bad_url_scheme": "허용되지 않은 URL 스킴: {scheme}",
    "update.bad_host": "허용되지 않은 다운로드 호스트: {host}",
    "update.bad_asset_name": "비정상 자산 이름: {name}",
    "update.checksum_missing": "SHA-256 체크섬이 없어 무결성을 검증할 수 없습니다 — 설치 중단",
    "update.checksum_mismatch": "SHA-256 불일치: expected {expected}, got {actual}",
    "update.download_interrupted": "다운로드가 도중에 끊겼습니다({downloaded}/{total} bytes)",
    "update.download_failed": "업데이트 다운로드 실패",
}

# 여러 조각을 한 줄로 이을 때 쓰는 구분자. 구분자도 언어 설정이라 여기 둔다.
JOIN_SEPARATOR = " · "


def _prepare(params: dict[str, object]) -> dict[str, object]:
    """파라미터 이름의 **접미사가 포맷을 고른다**.

    도메인이 "179.4MB" 같은 문자열을 만들지 않게 하는 장치다 — 바이트 수만 넘기면
    단위 표기는 여기서 붙는다(단위 표기도 언어 설정이다).

    값이 `Message`면 그것도 문장으로 만든다 — 다른 예외의 사유를 한 문장에 담을 때
    (`error_message()`) 안쪽 문장도 번역돼야 한다.
    """
    out = dict(params)
    for name, value in params.items():
        if isinstance(value, Message):
            out[name] = render(value)
        elif name.endswith("_bytes") and isinstance(value, (int, float)):
            out[name] = format_bytes(value, unit=ByteUnit.MB)
    return out


def render(msg: Message | str | None) -> str:
    """문장 하나를 만든다. 실패해도 예외를 내지 않는다(모듈 설명 참조).

    **문자열은 그대로 돌려준다.** 한 줄에 `Message`와 외부에서 온 값(가수 이름·장르처럼
    번역할 것이 없는 문자열)이 섞여 오는 경우가 있어서다(앨범 요약 조각).
    """
    if msg is None:
        return ""
    if isinstance(msg, str):
        return msg
    template = _TEMPLATES.get(msg.key)
    if template is None:
        logger.warning("표시 문구 템플릿이 없다: %s", msg.key)
        return msg.key
    try:
        return tr(template).format(**_prepare(msg.as_dict()))
    except (KeyError, IndexError, ValueError):
        # 파라미터가 모자라거나 형식이 안 맞는다. 채우지 못한 원문이라도 돌려준다.
        logger.exception("표시 문구를 채우지 못했다: %s", msg.key)
        return tr(template)


def render_all(msgs: Sequence[Message | str], sep: str = JOIN_SEPARATOR) -> str:
    """여러 조각을 한 줄로 잇는다(필터 요약 등)."""
    return sep.join(render(m) for m in msgs)


def describe_error(exc: BaseException | None) -> str:
    """예외 → 화면에 올릴 사유. **예외를 내지 않는다.**

    `DisplayError`는 `.message`를 문장으로 만들고, 그 밖의 예외는 예전처럼 `str(exc)`다
    (yt-dlp·네트워크가 준 원문 — 번역할 방법이 없다). 뷰모델이
    `error_occurred.emit(str(exc))` 대신 이것을 부른다.
    """
    if exc is None:
        return ""
    try:
        if isinstance(exc, DisplayError):
            return render(exc.message)
        return str(exc)
    except Exception:
        # __str__이 터지는 예외도 있다. 오류를 알리려다 두 번째 오류로 죽지 않는다.
        logger.exception("오류 사유를 문장으로 만들지 못했다: %s", type(exc).__name__)
        return type(exc).__name__
