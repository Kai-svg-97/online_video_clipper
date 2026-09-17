"""미디어 서버(Plex·Jellyfin·Kodi)가 읽는 사이드카 파일의 **순수 생성 규칙** — I/O 없음.

이 앱이 모아 둔 메타데이터(제목·채널·설명·태그·업로드일·노래 정보)는 지금까지 앱
안에서만 의미가 있었다. 같은 폴더에 `.nfo`를 써 두면 미디어 서버가 그 값을 그대로
읽어, 이 앱이 **서버의 수집기**가 된다.

**왜 `.nfo`인가**: Kodi가 정한 XML 형식이고 Jellyfin·Emby가 그대로 읽는다. Plex도
XBMC/Kodi 에이전트로 읽을 수 있다. 공통 분모가 이것뿐이다.

**두 가지 형식을 쓴다**:

- `musicvideo` — 노래로 표시된 영상. 가수·앨범이 태그로 들어가 음악 라이브러리에서
  제대로 묶인다.
- `movie` — 그 외 전부. 한 편짜리 영상에 가장 널리 지원되는 형식이다.

`episodedetails`(TV 방송)는 쓰지 않는다 — 시즌·회차 번호를 요구하는데 YouTube
영상에는 그런 것이 없어, 억지로 만들면 서버가 엉뚱하게 묶는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from xml.sax.saxutils import escape

# Kodi는 상영 시간을 **분** 단위로 읽는다. 초를 그대로 넣으면 3분짜리가 180분이 된다.
_SECONDS_PER_MINUTE = 60


@dataclass(frozen=True, slots=True)
class MediaServerEntry:
    """사이드카 한 건에 필요한 값. 저장소 형태와 무관한 평평한 값들이다."""

    title: str
    file_path: str
    url: str = ""
    channel_name: str = ""
    description: str = ""
    published_at: str = ""          # ISO8601 또는 "YYYYMMDD"
    duration_sec: int = 0
    tags: tuple[str, ...] = ()
    thumbnail_path: str = ""
    # 노래 정보 — 있으면 musicvideo 로 쓴다.
    is_song: bool = False
    artist: str = ""
    album: str = ""
    song_title: str = ""
    release_year: str = ""

    def display_title(self) -> str:
        """음악 라이브러리에는 곡 제목을, 그 외에는 영상 제목을 쓴다.

        영상 제목에는 "(Official MV)" 같은 꼬리표가 붙어 있어, 음악으로 묶을 때는
        곡 제목이 훨씬 낫다. 곡 제목이 비어 있으면 영상 제목으로 되돌아간다.
        """
        if self.is_song and self.song_title.strip():
            return self.song_title
        return self.title


def _text(tag: str, value: object) -> str:
    """빈 값은 **아예 쓰지 않는다** — 빈 태그를 넣으면 서버가 '값이 있다'로 읽어
    기존 정보를 지운다(실제로 Jellyfin이 그렇게 동작한다)."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return f"  <{tag}>{escape(text)}</{tag}>\n"


def normalize_date(raw: str) -> str:
    """업로드일을 `YYYY-MM-DD`로. 알아볼 수 없으면 빈 문자열.

    저장된 값이 ISO8601(`2024-05-01T12:00:00Z`)일 때도, yt-dlp가 주는
    `20240501` 형태일 때도 있어 둘 다 받는다.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return text[:10] if len(text) >= 10 and text[4] == "-" else ""


def build_nfo(entry: MediaServerEntry) -> str:
    """`.nfo` XML 한 편. 노래면 `musicvideo`, 아니면 `movie`."""
    root = "musicvideo" if entry.is_song else "movie"
    body = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<{root}>\n']

    body.append(_text("title", entry.display_title()))
    body.append(_text("plot", entry.description))
    date = normalize_date(entry.published_at)
    body.append(_text("premiered", date))
    if date:
        body.append(_text("year", date[:4]))
    elif entry.release_year:
        body.append(_text("year", entry.release_year))
    if entry.duration_sec:
        body.append(_text("runtime", max(1, entry.duration_sec // _SECONDS_PER_MINUTE)))
    body.append(_text("studio", entry.channel_name))

    if entry.is_song:
        body.append(_text("artist", entry.artist or entry.channel_name))
        body.append(_text("album", entry.album))
    else:
        # movie 에는 artist 가 없다 — 채널을 감독으로 넣어야 서버 목록에서 구분된다.
        body.append(_text("director", entry.channel_name))

    for tag in entry.tags:
        body.append(_text("tag", tag))
    if entry.thumbnail_path:
        body.append(_text("thumb", entry.thumbnail_path))
    if entry.url:
        # 서버가 중복을 가려내는 열쇠. 같은 영상을 두 번 넣어도 하나로 본다.
        body.append(f'  <uniqueid type="youtube" default="true">{escape(entry.url)}</uniqueid>\n')

    body.append(f"</{root}>\n")
    return "".join(body)


def nfo_path_for(media_path: str) -> str:
    """미디어 파일 옆의 `.nfo` 경로 — 확장자만 바꾼다(서버의 규약)."""
    dot = media_path.rfind(".")
    slash = max(media_path.rfind("/"), media_path.rfind("\\"))
    if dot <= slash:                      # 확장자가 없는 파일
        return media_path + ".nfo"
    return media_path[:dot] + ".nfo"


@dataclass(frozen=True, slots=True)
class M3uEntry:
    """재생목록 한 줄 — 파일 경로와 표시용 제목·길이."""

    path: str
    title: str = ""
    duration_sec: int = 0


def build_m3u(entries: list[M3uEntry]) -> str:
    """`#EXTM3U` 재생목록.

    길이를 모르면 `-1`을 쓴다(형식이 정한 값이다 — 0을 넣으면 플레이어가 곧바로
    다음 곡으로 넘어간다). 내용은 UTF-8로 저장해야 한다.
    """
    lines = ["#EXTM3U"]
    for entry in entries:
        duration = int(entry.duration_sec) if entry.duration_sec else -1
        title = (entry.title or "").replace("\n", " ").strip()
        lines.append(f"#EXTINF:{duration},{title}")
        lines.append(entry.path)
    return "\n".join(lines) + "\n"
