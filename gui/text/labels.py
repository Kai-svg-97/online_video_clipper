"""닫힌 키 집합 → 표시 이름.

도메인은 영어 키를 갖고(`STATUS_OK = "ok"`, SponsorBlock 카테고리 값) 표시 이름은
여기가 갖는다. 프로젝트가 이미 세 번 내린 판단을 한곳으로 모은 것이다 —
`gui/panels/library/constants.py`의 `MATCH_FIELD_LABELS`, `gui/panels/album_panel.py`의
`ORIGIN_LABELS`, `gui/panels/detail/text_format.py`의 `_summary_status_labels()`.

**한 패널만 쓰는 라벨은 옮기지 않는다** — 위 셋은 지금 자리 그대로 둔다. 여기로
오는 것은 도메인에서 걷어낸, 여러 곳에서 쓰이는 라벨이다.

키마다 라벨이 있는지(그리고 남는 라벨이 없는지)는
`tests/unit/gui/test_label_coverage.py`가 지킨다 — 도메인에 키를 더하고 라벨을
빠뜨리면 화면에 키가 그대로 뜬다.

덩어리 C2에서 채워진다.
"""

from __future__ import annotations


# ── SponsorBlock 건너뛰기 구간 ────────────────────────────────────
# 키는 SponsorBlock API 의 category 값 그대로다(`domain/clip/sponsor.py`).
SPONSOR_CATEGORY_LABELS: dict[str, str] = {
    "sponsor": "스폰서 광고",
    "selfpromo": "자기 홍보·후원",
    "interaction": "구독 요청",
    "intro": "인트로·오프닝",
    "outro": "아웃트로·엔딩",
    "preview": "예고·재탕 요약",
    "filler": "잡담·곁가지",
    "music_offtopic": "음악 외 구간",
}


def sponsor_category_label(key: str) -> str:
    """모르는 카테고리는 키를 그대로 — API 가 새 값을 추가해도 화면이 비지 않는다."""
    return SPONSOR_CATEGORY_LABELS.get(key, key)


# ── 원본 확인 상태 ────────────────────────────────────────────────
# 키는 `domain/library/availability.py` 의 STATUS_* 상수다.
AVAILABILITY_LABELS: dict[str, str] = {
    "ok": "정상",
    "removed": "삭제됨",
    "private": "비공개",
    "unknown": "확인 불가",
}


def availability_label(status: str) -> str:
    return AVAILABILITY_LABELS.get(status, status)


# ── 복합 필터 프리셋 ──────────────────────────────────────────────
# (그룹, 키) → 표시 이름. 값(며칠 전부터·초 범위)은 `domain/library/filters.py` 에 있다.
FILTER_PRESET_LABELS: dict[tuple[str, str], str] = {
    ("date", "all"): "전체 기간",
    ("date", "7d"): "최근 1주",
    ("date", "30d"): "최근 1개월",
    ("date", "90d"): "최근 3개월",
    ("date", "365d"): "최근 1년",
    ("duration", "all"): "전체 길이",
    ("duration", "short"): "4분 미만",
    ("duration", "medium"): "4~20분",
    ("duration", "long"): "20분 이상",
    ("download", "all"): "전체",
    ("download", "yes"): "받아 둔 것만",
    ("download", "no"): "안 받은 것만",
    ("watched", "all"): "전체",
    ("watched", "yes"): "본 것만",
    ("watched", "no"): "안 본 것만",
}


def filter_preset_label(group: str, key: str) -> str:
    return FILTER_PRESET_LABELS.get((group, key), key)


# ── 포맷 변환 프리셋 ──────────────────────────────────────────────
# 키는 `domain/clip/presets.py` 의 ConvertPreset.key. (이름, 설명) 짝이다.
CONVERT_PRESET_LABELS: dict[str, tuple[str, str]] = {
    "mp4-1080p": ("일반 재생용 (1080p mp4)", "H.264+AAC — 폰·TV·차량에서 거의 항상 열립니다"),
    "mp4-720p": ("용량 줄이기 (720p mp4)", "같은 조합에 해상도만 낮춰 파일을 작게 만듭니다"),
    "mp4-480p": ("많이 줄이기 (480p mp4)", "화질을 크게 낮추는 대신 가장 작습니다"),
    "mp3": ("소리만 (mp3)", "어디서나 열리는 음원. 호환이 가장 넓습니다"),
    "m4a": ("소리만 (m4a)", "같은 용량에서 mp3보다 낫습니다. 애플 기기에 잘 맞습니다"),
}


def convert_preset_name(key: str) -> str:
    return CONVERT_PRESET_LABELS.get(key, (key, ""))[0]


def convert_preset_description(key: str) -> str:
    return CONVERT_PRESET_LABELS.get(key, (key, ""))[1]


# ── 음성 인식 모델 ────────────────────────────────────────────────
# 키는 `domain/library/transcribe.py` 의 TranscribeModel.key. (이름, 설명) 짝이다.
TRANSCRIBE_MODEL_LABELS: dict[str, tuple[str, str]] = {
    "tiny": ("가장 빠름 (tiny)", "빠르지만 정확도가 낮습니다. 무슨 말인지 훑어볼 때."),
    "base": ("권장 (base)", "속도와 정확도가 무난합니다. 대부분 이걸로 충분합니다."),
    "small": ("정확함 (small)", "느리지만 정확합니다. 저사양 PC에서는 오래 걸립니다."),
}


def transcribe_model_name(key: str) -> str:
    return TRANSCRIBE_MODEL_LABELS.get(key, (key, ""))[0]


def transcribe_model_note(key: str) -> str:
    return TRANSCRIBE_MODEL_LABELS.get(key, (key, ""))[1]


# ── 재생 화질 ─────────────────────────────────────────────────────
# 키는 `gui/widgets/player/constants.py` 의 `_QUALITY_OPTIONS` 첫 원소다.
# "1080p" 같은 키는 겉보기엔 표시 문자열이지만 어느 언어에서도 같은 ASCII 식별자다 —
# 진짜 문제는 `"자동"` 하나였고 그것만 `"auto"` 로 바뀌었다.
QUALITY_MENU_LABELS: dict[str, str] = {
    "auto": "자동 (최고 화질)",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
    "360p": "360p",
    "240p": "240p",
}


def quality_menu_label(key: str) -> str:
    return QUALITY_MENU_LABELS.get(key, key)


def quality_badge_text(key: str) -> str:
    """재생 중 화질 배지 — **자동일 때는 비운다.**

    "자동"은 실제 화질이 아니라 고르는 방식이라, 배지에 적으면 약속하지 못할 값을
    적는 셈이 된다. 예전에는 이 판단이 `if short == "자동"` 이라는 문자열 비교로
    흩어져 있었다.
    """
    return "" if key == "auto" else key


# ── 자막 트랙 ─────────────────────────────────────────────────────
# 자동 번역 대상 언어 이름은 **자국어 표기**를 쓴다 — 영어 UI 사용자도 "日本語"를
# 보는 편이 "Japanese"보다 고르기 쉽다(언어 선택기의 일반적인 관행이다).
LANGUAGE_NAMES: dict[str, str] = {
    "ko": "한국어",
    "en": "English",
    "ja": "日本語",
    "zh-Hans": "中文(简体)",
    "es": "Español",
}


def subtitle_track_label(track) -> str:
    """자막 메뉴에 적는 이름.

    **`auto` 플래그만 본다.** 예전에는 YouTube가 준 트랙 이름에 "자동"이 들어 있는지
    검사했는데, 그 이름은 사용자의 YouTube 계정 언어를 따라가므로(영어 계정이면
    "Korean (auto-generated)") 믿을 수 없는 판정이었다.
    """
    base = track.name or track.lang
    if track.auto:
        base = f"{base} (자동 생성)"
    if track.translate_to:
        target = LANGUAGE_NAMES.get(track.translate_to, track.translate_to)
        base = f"{base} → {target} 번역"
    return base


# ── 빌트인 다운로드 프리셋 ────────────────────────────────────────
# 사용자가 만든 프리셋의 이름은 **사용자 데이터**라 저장된 값을 그대로 쓴다.
# 빌트인만 키가 고정이라 여기서 이름을 얹는다.
BUILTIN_PRESET_LABELS: dict[str, str] = {
    "builtin:archive": "보관용 (1080p·자막·챕터)",
    "builtin:music": "음악 (m4a·표지·태그)",
    "builtin:light": "가볍게 (720p·광고 잘라내기)",
}

# 이름을 비워 저장할 때 대신 쓰는 이름 — 도메인이 아니라 화면이 정한다.
DEFAULT_PRESET_NAME = "내 프리셋"
DEFAULT_SAVED_SEARCH_NAME = "저장된 검색"


def download_preset_name(preset) -> str:
    """빌트인은 표에서, 사용자 프리셋은 저장된 이름 그대로."""
    return preset.name or BUILTIN_PRESET_LABELS.get(preset.key, preset.key)


# ── 챕터 ──────────────────────────────────────────────────────────
def chapter_title(title: str, index: int) -> str:
    """제목 없는 챕터에 붙이는 이름. 도메인은 빈 제목을 그대로 둔다."""
    return title or f"챕터 {index}"
