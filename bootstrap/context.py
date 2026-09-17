"""조립 결과를 담는 컨텍스트 객체들.

`main()` 안에서 지역 변수 90여 개로 흘러다니던 것들을 **바운디드 컨텍스트별 묶음**으로
묶는다. 목적은 두 가지다:

1. **`main()`이 조립 목록이 아니라 순서만 말하게 한다.** 예전 `main()`은 609줄이고
   그 안에 핸들러 생성이 91번 있었다. 기능을 하나 추가하면 이 함수를 고쳐야 했고,
   최근 6개월에 39번 고쳐졌다. 지금은 어느 컨텍스트의 조립을 고칠지가 파일로
   갈라져 있어 서로 부딪히지 않는다.
2. **시그니처 폭발을 줄인다.** `MainWindow`는 뷰모델을 낱개로 13개 받았고 절반이
   타입 힌트 없는 `song_vm=None` 꼴이었다. 뷰모델을 하나 추가하면 `main()`·
   `MainWindow`·`LibraryPanel` **세 곳**의 시그니처를 고쳐야 했다. 지금 `MainWindow`
   는 `ViewModels` 묶음 하나를 받으므로 그 한 곳이 빠졌다.

   **`LibraryPanel`은 일부러 낱개 인자를 유지했다** — 테스트가
   `LibraryPanel(vm=library_vm)`처럼 필요한 것만 넣어 최소 구성으로 만드는데,
   전체 묶음을 요구하면 테스트마다 쓰지도 않는 뷰모델 10개를 만들어야 한다.
   그래서 뷰모델 추가는 여전히 `ViewModels`·`bootstrap/view_models.py`·
   `LibraryPanel`을 함께 손대야 한다(세 곳 → 여전히 세 곳이지만, `MainWindow`가
   묶음을 받아 **낱개 인자 13개가 사라졌다**는 것이 실익이다).

## 왜 frozen인가

조립은 시작할 때 한 번 일어나고 그 뒤로는 읽기만 한다. 실행 중에 핸들러를 바꿔
끼우는 경로는 없다(YouTube 인증조차 `Services.youtube_api` 콜백 안에서 lazy로
해석하고 캐시할 뿐, 컨텍스트 자체를 교체하지 않는다). 그래서 얼려 두면 "여기 값이
언제 바뀌나"를 의심할 필요가 없어진다.

`slots=True`는 저사양 PC 대응 규칙(값 객체에 `__slots__`)과 같은 이유다 — 다만 이
객체들은 한 개씩만 만들어지므로 메모리보다 **오타 방지**가 실익이다(없는 필드에
값을 넣으면 즉시 터진다).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 뷰모델 묶음은 **프레젠테이션 계층이 소유한다** — 조립 루트가 GUI를 의존하는 것은
# 정상이지만 그 반대는 레이어 역전이다(gui/view_models/bundle.py 참조).
# 여기서는 조립부가 한곳에서 꺼내 쓰도록 재수출만 한다.
from gui.view_models.bundle import ViewModels


@dataclass(frozen=True, slots=True)
class Repositories:
    """도메인 리포지토리 묶음.

    클라우드 동기화가 연결돼 있으면 일부가 `Recording*` 데코레이터로 감싸인 채
    들어온다(`infrastructure/sync/recording_repository.py`). 받는 쪽은 그 차이를
    몰라도 되며, 그래서 감싸는 판단은 `bootstrap/persistence.py` 한 곳에만 있다.

    `album`은 파생 캐시라 **동기화 캡처 대상이 아니다** — 감싸지 않는다.
    """

    video: Any
    download: Any
    clip: Any
    channel: Any
    playlist: Any
    folder: Any
    song: Any
    album: Any


@dataclass(frozen=True, slots=True)
class Services:
    """인프라 서비스·어댑터 묶음.

    `youtube_api`는 어댑터가 아니라 **어댑터를 돌려주는 콜백**이다. YouTube 인증은
    keyring을 건드려 200~300ms가 걸리므로 시작 시점에 해석하지 않고, 실제로 YouTube
    기능을 쓰는 순간에 한 번만 해석해 캐시한다(미인증이면 `None`이 캐시된다). 이
    lazy 규약은 기존 동작과 같다 — 인증은 원래도 재시작 후에만 전 핸들러에 반영됐다.
    """

    event_bus: Any
    media_source: Any            # YtDlpAdapter — domain.shared.ports.IMediaSource
    clip_extractor: Any          # FfmpegAdapter — IClipExtractor
    audio_tagger: Any            # MutagenAudioTagger — IAudioTagger
    youtube_oauth: Any
    youtube_api: Callable[[], Any | None]
    auth_service: Any
    lyrics_providers: Any
    translator: Any
    summary_source: Any          # GeminiExtractor — ISummarySource
    album_provider: Any
    sync_service: Any
    download_queue: Any


@dataclass(frozen=True, slots=True)
class LibraryHandlers:
    """라이브러리(영상·카테고리·태그) 유스케이스."""

    add_video: Any
    update_video: Any
    delete_video: Any
    mark_watched: Any
    update_position: Any
    enrich_video: Any
    assign_category: Any
    create_category: Any
    rename_category: Any
    delete_category: Any
    move_category: Any
    delete_tag: Any
    refresh_category_metadata: Any
    refresh_video_metadata: Any
    refresh_thumbnail: Any
    import_youtube_playlist_to_category: Any
    get_videos: Any
    search_videos: Any
    get_categories: Any
    get_tags: Any
    get_video_detail: Any
    get_downloaded_formats: Any
    get_video_id_by_url: Any
    get_category_order: Any
    set_category_order: Any
    stats: Any
    # 라이브러리 정리 — (중복찾기, 끊긴파일찾기, 일괄삭제) 콜백 3종.
    # 찾아 주기만 하고 삭제는 사용자가 고른 것만 수행한다(자동 삭제 없음).
    cleanup_fns: tuple[Callable[..., Any], ...]


@dataclass(frozen=True, slots=True)
class DownloadHandlers:
    """다운로드 큐·이력 유스케이스."""

    start: Any
    cancel: Any
    get_queue: Any
    get_history: Any
    event_bridge: Any


@dataclass(frozen=True, slots=True)
class ClipHandlers:
    """클립 추출 유스케이스."""

    extract: Any
    extract_many: Any
    delete: Any
    get_clips: Any
    get_chapters: Any


@dataclass(frozen=True, slots=True)
class MonitoringHandlers:
    """채널 구독·모니터링 유스케이스."""

    subscribe: Any
    unsubscribe: Any
    set_rule: Any
    get_subscriptions: Any
    import_youtube_subscriptions: Any


@dataclass(frozen=True, slots=True)
class PlaylistHandlers:
    """재생목록·폴더·구독 피드·추천 유스케이스.

    피드·채널·추천이 재생목록과 한 묶음인 것은 셋 다 **YouTube API lazy provider**를
    공유하기 때문이다(`Services.youtube_api`). 조립 의존이 같은 것끼리 모아 두면
    인증 규약을 바꿀 때 한 파일만 보면 된다.
    """

    create: Any
    delete: Any
    rename: Any
    add_video: Any
    remove_video: Any
    reorder: Any
    move_video: Any
    add_url: Any
    import_youtube: Any
    copy_youtube_to_local: Any
    push_to_youtube: Any
    get_playlists: Any
    get_items: Any
    get_youtube_playlists: Any
    create_folder: Any
    rename_folder: Any
    delete_folder: Any
    move_to_folder: Any
    get_folders: Any
    get_feed: Any
    get_channel_videos: Any
    get_channel_infos: Any
    get_recommendations: Any


@dataclass(frozen=True, slots=True)
class SongHandlers:
    """노래 정보·가사 유스케이스.

    `fetch`(체인 검색)는 **라이브러리 등록 경로도 쓴다** — `AddVideoHandler`가 등록
    시 노래를 감지해 메타데이터를 기록하고, `EnrichVideoHandler`가 등록 직후 가사를
    채운다. 그래서 조립 순서상 song이 library보다 **먼저** 만들어져야 한다
    (`bootstrap/handlers/__init__.py`가 그 순서를 명시한다).
    """

    fetch: Any
    get_info: Any
    search_candidates: Any
    apply_candidate: Any
    set_flag: Any
    update_field: Any
    update_lyrics: Any
    translate_lyrics: Any
    set_lyrics_offset: Any
    find_video_ids: Any
    list_sources: Any
    add_source: Any
    update_source: Any
    delete_source: Any
    reorder_sources: Any
    # 다운로드 완료 이벤트 구독자 — 호출되지 않고 **살아 있기만** 하면 된다.
    # 필드로 붙들지 않으면 조립이 끝나는 순간 GC돼 구독이 조용히 사라진다.
    tag_writer: Any


@dataclass(frozen=True, slots=True)
class AlbumHandlers:
    """앨범 보기 유스케이스(노래 정보에서 파생된 그룹)."""

    get_albums: Any
    get_detail: Any
    fill_tracks: Any
    resolve_unknown: Any
    add_tracks: Any
    remove_track_link: Any


@dataclass(frozen=True, slots=True)
class TransferHandlers:
    """라이브러리 가져오기/내보내기 유스케이스."""

    export: Any
    preview: Any
    detect_conflicts: Any
    do_import: Any


@dataclass(frozen=True, slots=True)
class UpdaterHandlers:
    """자동 업데이트 유스케이스."""

    check: Any
    download: Any


@dataclass(frozen=True, slots=True)
class Handlers:
    """컨텍스트별 유스케이스 묶음 전체."""

    library: LibraryHandlers
    download: DownloadHandlers
    clip: ClipHandlers
    monitoring: MonitoringHandlers
    playlist: PlaylistHandlers
    song: SongHandlers
    album: AlbumHandlers
    transfer: TransferHandlers
    updater: UpdaterHandlers


@dataclass(frozen=True, slots=True)
class AppGraph:
    """조립 결과 전체 — 리포지토리·서비스·핸들러·뷰모델.

    테스트는 이 하나만 만들어 보면 조립이 성립하는지 알 수 있다. 예전에는 조립이
    `main()` 안에만 있어서 **조립 자체를 확인할 방법이 없었다** — main.py를 겨냥한
    테스트는 OAuth 조립 헬퍼와 종료 tail 배치 줄, 넷뿐이었고 핸들러 91개와 뷰모델
    배선은 앱을 띄워 그 기능을 눌러 봐야 알 수 있었다(6개월간 39번 바뀐 파일이다).
    """

    repositories: Repositories
    services: Services
    handlers: Handlers
    view_models: ViewModels
