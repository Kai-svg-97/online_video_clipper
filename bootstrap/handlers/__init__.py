"""컨텍스트별 유스케이스 조립을 순서대로 엮는다.

## 조립 순서가 여기 명시돼 있다

예전에는 `main()` 안 300여 줄에 걸쳐 핸들러 91개가 늘어서 있었고, 어느 것이 어느
것을 필요로 하는지는 **줄 순서에만** 담겨 있었다. 중간에 한 줄을 위로 옮기면
조용히 깨지는 구조였다(실제로 `cleanup_fns`는 아직 대입되지 않은
`delete_video`를 클로저로 참조하고 있었다 — 동작은 했지만 읽는 사람이 알 수 없다).

지금은 의존이 **함수 인자로 드러난다**:

* `song` → `library` : 등록 시 노래 감지·가사 보강에 song 체인을 쓴다.
* `library` → `download` : 다운로드 완료 후 라이브러리에 등록한다.
* `library` → `playlist` : URL 추가·YouTube 가져오기가 등록 경로를 탄다.
* `library` → `album` : 수록곡 담기가 등록 + 노래 정보 기록을 함께 한다.

나머지(clip·monitoring·transfer·updater)는 다른 컨텍스트에 의존하지 않는다.
"""

from __future__ import annotations

from bootstrap.context import Handlers, Repositories, Services
from bootstrap.handlers import (
    album,
    clip,
    download,
    library,
    monitoring,
    playlist,
    song,
    transfer,
    updater,
)


def build_handlers(repos: Repositories, services: Services) -> Handlers:
    """모든 컨텍스트의 유스케이스를 조립한다.

    순서를 바꾸면 `NameError`가 아니라 **인자 누락**으로 즉시 드러난다.
    """
    song_h = song.build(repos, services)
    library_h = library.build(repos, services, song_h)
    return Handlers(
        song=song_h,
        library=library_h,
        download=download.build(repos, services, library_h),
        clip=clip.build(repos, services),
        monitoring=monitoring.build(repos, services),
        playlist=playlist.build(repos, services, library_h),
        album=album.build(repos, services, library_h),
        transfer=transfer.build(repos, services),
        updater=updater.build(),
    )


__all__ = ["build_handlers"]
