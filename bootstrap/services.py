"""인프라 서비스·어댑터 조립.

`persistence.py`와 같은 이유로 임포트가 무겁다 — `main()`이 스플래시를 띄운 뒤에
임포트한다(그 파일의 "임포트가 무거운 것은 의도다" 항목 참조).
"""

from __future__ import annotations

import logging
from pathlib import Path

from config.settings import DATA_DIR
from infrastructure.auth.youtube_auth import YouTubeAuthService
from infrastructure.browser.gemini_extractor import GeminiExtractor
from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter
from infrastructure.event_bus import EventBus
from infrastructure.ffmpeg.ffmpeg_adapter import FfmpegAdapter
from infrastructure.song.audio_tagger import MutagenAudioTagger
from infrastructure.downloader.availability import YouTubeAvailabilityChecker
from infrastructure.sponsorblock.client import SponsorBlockClient
from infrastructure.subtitle.whisper_transcriber import WhisperTranscriber
from infrastructure.song.album_providers import build_default_album_provider
from infrastructure.song.lyrics_providers import build_default_providers
from infrastructure.song.translator import DeepTranslatorAdapter
from infrastructure.sync.keyring_secret_store import KeyringSecretStore
from infrastructure.sync.sync_service import SyncService
from infrastructure.youtube.oauth_adapter import YouTubeOAuthAdapter
from infrastructure.youtube.oauth_client_config import find_youtube_oauth_config

from domain.download.aggregates import DownloadQueueAggregate

from bootstrap.context import Services

logger = logging.getLogger(__name__)


def build_youtube_oauth(db) -> YouTubeOAuthAdapter:
    """번들된 Desktop OAuth 클라이언트로 어댑터를 만든다.

    클라이언트 설정 파일이 없어도 `has_client_config() == False`인 어댑터를 돌려주어
    앱 시작을 막지 않는다(YouTube API 의존 기능만 비활성). 다만 파일이 **있는데
    형식이 틀린** 경우는 `find_youtube_oauth_config()`가 `OAuthClientConfigError`를
    던지도록 설계돼 있으므로 여기서 잡지 않는다 — 조용히 건너뛰면 "왜 로그인이 안
    되는지" 알 수 없어진다.

    **비밀 저장소는 YouTube 전용 키를 쓴다.** `infrastructure.sync`의
    `build_secret_store()`는 동기화 provider용이라 keyring 서비스명과 파일 경로가
    다르다 — 그걸 쓰면 기존 사용자의 저장된 토큰을 찾지 못해 로그아웃된 것처럼
    보인다.
    """
    yt_secret_store = KeyringSecretStore(
        "online-video-clipper.youtube-oauth",
        Path(DATA_DIR) / "secrets" / "youtube_oauth.json",
    )
    return YouTubeOAuthAdapter(
        db,
        yt_secret_store,
        client_config_path=find_youtube_oauth_config(),
    )


def _make_youtube_api_provider(yt_oauth):
    """호출 시점에 한 번만 인증을 해석하는 콜백을 만든다(lazy binding).

    YouTube 인증은 keyring을 건드려 **200~300ms**가 걸리므로 시작 시점에 하지 않고,
    실제로 YouTube 기능을 쓰는 순간(피드·채널 클릭, 재생목록 push 등)에만 해석한다.
    결과는 **성공·실패 모두 캐시**해 세션 중 반복 keyring 접근을 만들지 않는다 —
    인증은 원래도 재시작 후에만 전 핸들러에 반영됐으므로 기존 동작과 같다.

    예전에는 `main()` 안의 클로저 + `nonlocal`이었다. 모듈 함수로 옮기면서 상태를
    리스트 한 칸에 담는데, 클로저 변수 대신 쓰는 흔한 관용구다(`nonlocal`을
    쓰려면 중첩 함수가 또 필요하다).
    """
    cache: list = [None, False]   # [adapter, resolved]

    def provider():
        if not cache[1]:
            from infrastructure.youtube.youtube_api_adapter import YouTubeApiAdapter

            creds = yt_oauth.get_credentials()
            cache[0] = YouTubeApiAdapter(creds) if creds is not None else None
            cache[1] = True
        return cache[0]

    return provider


def build_services(db) -> Services:
    """인프라 어댑터를 모아 `Services`로 만든다.

    `GeminiExtractor`는 등록 후 자동 보강과 다운로드 완료 캡처가 **공유**한다 —
    Playwright 브라우저를 띄우는 무거운 자원이라 인스턴스를 하나만 둔다.
    """
    yt_oauth = build_youtube_oauth(db)
    return Services(
        event_bus=EventBus(),
        media_source=YtDlpAdapter(),
        clip_extractor=FfmpegAdapter(),
        audio_tagger=MutagenAudioTagger(),
        skip_source=SponsorBlockClient(),
        availability_source=YouTubeAvailabilityChecker(),
        # 모델을 올리지 않는 가벼운 객체다(무거운 import 는 첫 전사 때).
        transcriber=WhisperTranscriber(),
        youtube_oauth=yt_oauth,
        youtube_api=_make_youtube_api_provider(yt_oauth),
        auth_service=YouTubeAuthService(),
        lyrics_providers=build_default_providers(),
        translator=DeepTranslatorAdapter(),
        summary_source=GeminiExtractor(),
        album_provider=build_default_album_provider(),
        sync_service=SyncService(db),
        download_queue=DownloadQueueAggregate(),
    )
