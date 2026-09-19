"""다운로드 프리셋 — **순수 값 객체와 기본 묶음**. 설정도 저장소도 모른다.

같은 사람이 영상을 받는 방식은 몇 가지로 갈린다 — 보관할 것은 화질 높게 자막까지,
음악은 음원만 태그 붙여서, 잠깐 볼 것은 가볍게. 지금은 전역 기본값 하나뿐이라 그때마다
설정 화면을 오가야 한다. 이름 붙인 묶음을 두고 고르게 한다.

## 무엇을 담고 무엇을 담지 않나

담는 것은 **어떤 파일을 원하는가**다(화질·형식·자막·굽기). 담지 않는 것은 **어떻게
받는가**다(속도 제한·프록시·조각 수) — 그건 회선의 성질이라 무엇을 받든 같고,
프리셋마다 따로 두면 "왜 이 프리셋만 느리지"가 된다.

## 왜 내장 프리셋을 두나

빈 목록에서 시작하면 사용자가 무엇을 만들 수 있는지 모른다. 흔한 세 가지를 미리
두되 **지울 수 있게** 한다 — 안 쓰는 항목이 목록에 남아 고르기를 방해하면 안 된다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

MAX_NAME_LEN = 30
MAX_PRESETS = 20

# 내장 프리셋의 키 — 사용자가 만든 것과 구분해 "되돌리기"를 지원한다.
BUILTIN_PREFIX = "builtin:"


@dataclass(frozen=True, slots=True)
class DownloadPreset:
    """이름 붙인 다운로드 방식 하나.

    필드는 `DownloadSettings` 중 **파일의 모양을 정하는 것들**만이다.
    """

    key: str = ""
    name: str = ""
    quality: str = "1080p"
    fmt: str = "mp4"
    subtitle_langs: str = ""          # "ko,en" — 빈 문자열이면 자막을 받지 않는다
    include_thumbnail: bool = True
    include_metadata: bool = True
    embed_subtitles: bool = True
    embed_thumbnail: bool = True
    embed_chapters: bool = True
    sponsorblock_remove: bool = False

    @property
    def is_builtin(self) -> bool:
        return self.key.startswith(BUILTIN_PREFIX)

    def to_payload(self) -> dict:
        return asdict(self)

    @classmethod
    def from_payload(cls, data: object) -> "DownloadPreset | None":
        """저장된 값 → 프리셋. **깨져 있으면 None**(그 항목만 빠진다).

        앱을 오르내리며 필드가 바뀌거나 사용자가 설정 파일을 손볼 수 있는데, 그때
        프리셋 하나 때문에 목록 전체가 안 뜨면 안 된다.
        """
        if not isinstance(data, dict):
            return None
        known = {f for f in cls.__slots__}
        clean = {k: v for k, v in data.items() if k in known}
        if not clean.get("name"):
            return None
        try:
            return cls(**clean)
        except TypeError:
            return None


BUILTIN_PRESETS: tuple[DownloadPreset, ...] = (
    DownloadPreset(
        key=f"{BUILTIN_PREFIX}archive",
        name="보관용 (1080p·자막·챕터)",
        quality="1080p", fmt="mp4", subtitle_langs="ko,en",
        embed_subtitles=True, embed_thumbnail=True, embed_chapters=True,
    ),
    DownloadPreset(
        key=f"{BUILTIN_PREFIX}music",
        name="음악 (m4a·표지·태그)",
        quality="best", fmt="m4a", subtitle_langs="",
        embed_subtitles=False, embed_thumbnail=True, embed_chapters=False,
    ),
    DownloadPreset(
        key=f"{BUILTIN_PREFIX}light",
        name="가볍게 (720p·광고 잘라내기)",
        quality="720p", fmt="mp4", subtitle_langs="",
        embed_subtitles=False, embed_thumbnail=False, embed_chapters=False,
        sponsorblock_remove=True,
    ),
)


def normalize_name(name: str) -> str:
    return " ".join((name or "").split())[:MAX_NAME_LEN]


def unique_name(name: str, existing: list[str]) -> str:
    """겹치면 번호를 붙인다 — 저장을 거절하면 사용자가 뭘 고쳐야 할지 모른다."""
    base = normalize_name(name) or "내 프리셋"
    taken = set(existing)
    if base not in taken:
        return base
    for i in range(2, MAX_PRESETS + 2):
        candidate = normalize_name(f"{base} {i}")
        if candidate not in taken:
            return candidate
    return base


def merge(builtin: tuple[DownloadPreset, ...], saved: list[DownloadPreset],
          hidden_keys: list[str]) -> list[DownloadPreset]:
    """내장 + 사용자 프리셋 목록.

    같은 키면 **사용자 것이 이긴다**(내장을 고쳐 쓴 경우). 숨긴 내장은 빼되,
    사용자가 같은 키로 고쳐 뒀다면 그것은 남긴다 — 숨김은 '원래 것'에만 걸린다.
    """
    by_key = {p.key: p for p in builtin if p.key not in set(hidden_keys)}
    for preset in saved:
        by_key[preset.key or preset.name] = preset
    return list(by_key.values())


def find(presets: list[DownloadPreset], key: str) -> DownloadPreset | None:
    """키로 찾는다(없으면 None) — 설정이 낡아 사라진 프리셋을 가리킬 수 있다."""
    return next((p for p in presets if p.key == key), None)


# 설정 화면의 화질 콤보는 yt-dlp 포맷 선택자를 담고(`bestvideo[height<=1080]...`),
# 프리셋은 `Quality` 값("1080p")을 쓴다. 그 사이를 옮긴다.
_SELECTOR_HEIGHTS: dict[str, str] = {
    "2160": "2160p",
    "1080": "1080p",
    "720": "720p",
    "480": "480p",
    "360": "360p",
}


def quality_from_selector(selector: str) -> str:
    """yt-dlp 포맷 선택자 → 프리셋 화질 값.

    **모르는 높이는 "best"로 본다.** 예컨대 1440p는 `Quality`에 없는데, 가까운
    아래 값(1080p)으로 내리면 사용자가 고른 것보다 낮은 화질을 받게 된다 —
    모를 때는 낮추는 쪽이 아니라 "가능한 가장 좋은 것"으로 떨어지는 편이 안전하다.
    """
    text = selector or ""
    for height, value in _SELECTOR_HEIGHTS.items():
        if f"height<={height}" in text:
            return value
    return "best"
