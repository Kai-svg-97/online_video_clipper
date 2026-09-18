"""브라우저 북마크(HTML) 해석 — **순수 파싱**, 파일도 네트워크도 없다.

브라우저마다 내보내기 메뉴는 다르지만 결과 형식은 하나로 수렴한다 — Netscape
Bookmark File Format(1990년대 넷스케이프가 만든 것을 Chrome·Edge·Firefox·Safari가
그대로 쓴다). 그래서 파서 하나로 전부 받는다.

```html
<DT><H3>음악</H3>
<DL><p>
    <DT><A HREF="https://youtu.be/xxx" ADD_DATE="1700000000">제목</A>
</DL><p>
```

## 왜 정규식으로 읽나

이 형식은 **닫는 태그가 없다**(`<DT>`·`<p>`가 열린 채로 끝난다). 제대로 된 HTML이
아니라서 엄격한 파서는 구조를 잘못 잡거나 통째로 실패한다. 우리가 필요한 것은
`<A HREF>` 한 종류와 `<H3>` 폴더 이름뿐이라, 그 둘만 순서대로 훑는 편이 튼튼하다.

## 왜 '영상일 법한 것'을 표시만 하고 거르지 않나

이 앱은 yt-dlp를 쓰므로 1000개가 넘는 사이트를 받을 수 있다. 우리가 목록을 들고
거르면 **받을 수 있는 주소를 막게 된다**. 반대로 북마크 전부를 그냥 담으면 쇼핑몰·
문서 링크까지 라이브러리에 들어온다. 그래서 판단을 화면으로 넘긴다 — 흔한 영상
호스트는 미리 체크해 두고, 나머지는 사용자가 고른다.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

# 미리 체크해 둘 호스트 — "이건 확실히 영상"인 것만 둔다. 여기 없다고 못 받는 게
# 아니라, 체크를 사용자가 직접 한다는 뜻일 뿐이다.
LIKELY_VIDEO_HOSTS: tuple[str, ...] = (
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "soundcloud.com",
    "bilibili.com",
    "nicovideo.jp",
    "tiktok.com",
    "chzzk.naver.com",
    "tv.naver.com",
    "tv.kakao.com",
    "afreecatv.com",
)

_ANCHOR_RE = re.compile(
    r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_FOLDER_RE = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class Bookmark:
    """북마크 한 줄."""

    url: str
    title: str
    folder: str = ""          # 마지막으로 만난 폴더 이름(카테고리 제안용)

    @property
    def is_likely_video(self) -> bool:
        return is_likely_video(self.url)


def _text(raw: str) -> str:
    """태그를 걷고 엔티티를 풀어 사람이 읽는 문자열로."""
    return html.unescape(_TAG_RE.sub("", raw)).strip()


def is_likely_video(url: str) -> bool:
    """흔한 영상 호스트인가 — **거르는 기준이 아니라 미리 체크할 기준**이다."""
    lowered = (url or "").lower()
    if not lowered.startswith(("http://", "https://")):
        return False
    host = lowered.split("//", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == h or host.endswith("." + h) for h in LIKELY_VIDEO_HOSTS)


def parse_bookmarks(content: str) -> list[Bookmark]:
    """북마크 HTML → 북마크 목록(파일에 적힌 순서 그대로).

    `http(s)`가 아닌 것(`javascript:`·`place:`·`chrome://`)은 버린다 — 받을 수 없고,
    목록에 섞이면 고르기만 번거로워진다. 같은 주소가 여러 폴더에 있으면 **처음 것만**
    남긴다(브라우저에서 같은 영상을 여러 폴더에 넣어 두는 일이 흔하다).
    """
    if not content:
        return []

    # 폴더 이름과 링크를 **한 줄에 섞어** 순서대로 훑는다. 그래야 각 링크가 어느
    # 폴더 아래 있었는지 알 수 있다(중첩 깊이까지는 보지 않는다 — 카테고리 제안에
    # 필요한 것은 '가장 가까운 폴더 이름' 하나다).
    events: list[tuple[int, str, str]] = []
    for m in _FOLDER_RE.finditer(content):
        events.append((m.start(), "folder", _text(m.group(1))))
    for m in _ANCHOR_RE.finditer(content):
        events.append((m.start(), "link", f"{m.group(1)}\n{_text(m.group(2))}"))
    events.sort(key=lambda e: e[0])

    out: list[Bookmark] = []
    seen: set[str] = set()
    folder = ""
    for _pos, kind, payload in events:
        if kind == "folder":
            folder = payload
            continue
        url, _, title = payload.partition("\n")
        url = html.unescape(url).strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(Bookmark(url=url, title=title or url, folder=folder))
    return out
