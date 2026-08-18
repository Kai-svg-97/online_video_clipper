"""중복 영상 판정 — 라이브러리 정리를 위한 순수 규칙(I/O 없음).

같은 영상이 여러 번 들어오는 경로가 실제로 여럿이다:

* 같은 YouTube 영상인데 **주소 형태가 다르다** — `youtu.be/ID`, `watch?v=ID`,
  재생목록 파라미터(`&list=…`)나 타임스탬프(`&t=30`)가 붙은 주소. URL 문자열만 비교하는
  중복 방지(`get_by_url`)는 이걸 못 잡는다.
* 같은 곡·영상을 **다른 채널이 다시 올린 것**(재업로드·공식/비공식). 이건 자동으로
  지우면 안 되고 사람이 골라야 하므로 '비슷함'으로만 묶는다.

그래서 두 종류를 구분해 돌려준다: `exact`(같은 영상이 확실 — 영상 ID 일치)와
`similar`(제목·채널이 같아 보임 — 사람이 확인할 것).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# youtu.be/ID · watch?v=ID · shorts/ID · embed/ID 를 모두 잡는다.
_YT_ID_RE = re.compile(
    r"(?:youtu\.be/|[?&]v=|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})"
)
_NON_WORD_RE = re.compile(r"[^0-9a-z가-힣]+")

DUPLICATE_EXACT = "exact"      # 같은 영상(영상 ID 일치)
DUPLICATE_SIMILAR = "similar"  # 제목·채널이 같아 보임(사람 확인 필요)


def youtube_video_id(url: str) -> str:
    """URL에서 YouTube 영상 ID를 뽑는다(못 뽑으면 빈 문자열)."""
    if not url:
        return ""
    match = _YT_ID_RE.search(url)
    return match.group(1) if match else ""


def normalize_title(title: str) -> str:
    """비교용 제목 — 대소문자·기호·공백을 지운다(표시에는 쓰지 않는다)."""
    if not title:
        return ""
    text = unicodedata.normalize("NFKC", title).lower()
    return " ".join(_NON_WORD_RE.sub(" ", text).split())


@dataclass(slots=True)
class DuplicateGroup:
    """같은 영상으로 보이는 묶음. `kind`가 판정 근거다."""

    kind: str                       # DUPLICATE_EXACT | DUPLICATE_SIMILAR
    key: str                        # 영상 ID 또는 정규화 제목
    items: list = field(default_factory=list)   # 입력으로 받은 객체 그대로

    @property
    def extra_count(self) -> int:
        """지워도 되는 개수(하나는 남긴다)."""
        return max(0, len(self.items) - 1)


def group_duplicates(videos: list) -> list[DuplicateGroup]:
    """영상 목록에서 중복 묶음을 찾는다.

    * 먼저 **영상 ID**로 묶는다(주소 형태만 다른 같은 영상 — 확실한 중복).
    * ID로 묶이지 않은 것들만 **제목+채널**로 다시 묶는다(비슷함). ID가 같은 것을
      제목으로 또 묶으면 같은 묶음이 두 번 나온다.
    * 혼자인 묶음은 중복이 아니므로 버린다.
    * 결과는 '지울 게 많은 묶음' 순으로 정렬해 정리 효과가 큰 것부터 보이게 한다.
    """
    by_id: dict[str, list] = {}
    rest: list = []
    for video in videos:
        vid = youtube_video_id(getattr(video, "url", ""))
        if vid:
            by_id.setdefault(vid, []).append(video)
        else:
            rest.append(video)

    groups: list[DuplicateGroup] = []
    for vid, items in by_id.items():
        if len(items) > 1:
            groups.append(DuplicateGroup(DUPLICATE_EXACT, vid, items))
        else:
            rest.extend(items)

    by_title: dict[tuple[str, str], list] = {}
    for video in rest:
        title = normalize_title(getattr(video, "title", ""))
        if not title:
            continue
        channel = normalize_title(getattr(video, "channel_name", "") or "")
        by_title.setdefault((title, channel), []).append(video)
    for (title, _channel), items in by_title.items():
        if len(items) > 1:
            groups.append(DuplicateGroup(DUPLICATE_SIMILAR, title, items))

    # 확실한 중복을 먼저, 그다음 지울 개수가 많은 순.
    groups.sort(key=lambda g: (g.kind != DUPLICATE_EXACT, -g.extra_count, g.key))
    return groups
