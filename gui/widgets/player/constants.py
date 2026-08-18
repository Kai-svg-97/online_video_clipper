"""플레이어 공용 상수 — 스트림 클라이언트 순서, 검증 요청 형식, 화질 목록.

검증 요청(`_PROBE_*`)은 **실제 재생 주체(ffmpeg)와 똑같아야** 한다: 열린 Range와
Lavf UA를 쓴다. yt-dlp 전용 헤더나 제한 범위로 확인하면 검증만 통과하고 재생은
실패하는 위양성이 난다(실측으로 겪은 문제).
"""

from __future__ import annotations

import logging





logger = logging.getLogger(__name__)


# YouTube 고화질(>360p)은 영상+오디오가 분리돼 ffmpeg 병합이 필요하다.
# Windows Media Foundation 호환을 위해 avc1(H.264)+m4a(AAC)를 우선 선택한다.
def _merge_fmt(h: int) -> str:
    return (
        f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
        f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
    )



# 스트림 URL을 받을 때 순서대로 시도할 YouTube 플레이어 클라이언트(None = yt-dlp 기본).
#
# 기본 클라이언트가 돌려준 googlevideo URL이 **간헐적으로 403**을 내는 것을 실측으로
# 확인했다(같은 영상이 어떤 때는 200, 어떤 때는 403 — PO token/SABR 전환기의 서버측
# 거부로 보인다). 이때 다른 클라이언트로 다시 받으면 정상 URL이 나온다. 예전에는 첫
# 시도가 실패하면 그대로 포기하고 브라우저를 열어버려, "앱에서 재생이 안 된다"는
# 체감이 컸다.
_STREAM_CLIENTS: tuple[str | None, ...] = (None, "android", "ios", "tv")

# URL 검증 요청은 **실제 재생 주체(Qt Multimedia의 FFmpeg 백엔드)와 똑같이** 보내야 한다.
#
# 실측: 같은 googlevideo URL이 `Range: bytes=0-1`(제한 범위)에는 206을, `Range: bytes=0-`
# (열린 범위 = ffmpeg가 파일을 열 때 보내는 요청)에는 403을 돌려주는 경우가 있다. 예전
# 검증은 제한 범위를 써서 통과시켰고, 정작 재생은 403으로 실패했다(위양성). 그래서
# **열린 범위**로 확인한다. 응답 본문은 읽지 않고 바로 닫으므로 대역폭 부담은 없다.
# yt-dlp 전용 헤더도 쓰지 않는다 — 같은 이유로 위양성을 만든다.
_PROBE_UA = "Lavf/61.7.100"          # FFmpeg가 보내는 기본 User-Agent

_PROBE_RANGE = "bytes=0-"            # FFmpeg가 파일을 열 때 쓰는 열린 범위

_PROBE_TIMEOUT = (5, 8)

# 재생 도중 QMediaPlayer가 오류를 낼 때 스트림을 다시 받아 시도할 횟수.
# 1회로 묶는 이유: 코덱 미지원처럼 다시 받아도 똑같이 실패하는 원인에서 무한 반복을 막는다.
_MAX_STREAM_RETRIES = 1

# (메뉴 라벨, yt-dlp 포맷, 버튼 단축 라벨, merge: 병합 필요 여부)
_QUALITY_OPTIONS = [
    ("자동 (빠른 재생)", "best[ext=mp4]/best", "자동",  False),
    ("1080p",           _merge_fmt(1080),     "1080p", True),
    ("720p",            _merge_fmt(720),      "720p",  True),
    ("480p",            _merge_fmt(480),      "480p",  True),
    ("360p",            "best[height<=360][ext=mp4]/best[height<=360]/best", "360p", False),
    ("240p",            "best[height<=240][ext=mp4]/best[height<=240]/best", "240p", False),
]

_DEFAULT_QUALITY_FMT = _QUALITY_OPTIONS[0][1]

_DEFAULT_QUALITY_MERGE = _QUALITY_OPTIONS[0][3]

# 재생 품질 단축 라벨 → 세로 해상도 ("자동"은 제한 없음)
_QUALITY_HEIGHTS: dict[str, int] = {
    "1080p": 1080, "720p": 720, "480p": 480, "360p": 360, "240p": 240,
}
