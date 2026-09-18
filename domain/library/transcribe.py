"""음성 인식(전사) 모델 카탈로그와 선택 규칙 — **순수 정의**, I/O 없음.

YouTube가 자막을 주지 않는 영상(오래된 영상, 자동 자막 미지원 언어)은 지금까지
자막 검색의 사각지대였다. 음성 인식으로 그 구멍을 메운다. 만들어진 자막은 **기존
자막 색인에 그대로 들어가므로**, 검색·시점 점프는 이미 있는 것을 쓴다.

**모델을 고르게 하는 이유**: 크기가 곧 정확도이자 시간이다. 이 앱의 목표 사양이
저사양 PC(4GB RAM)라, "가장 좋은 것"을 기본값으로 두면 대부분의 사용자에게
"몇 시간째 안 끝난다"가 된다. 그래서 무엇을 고르는지 **디스크·속도로 설명**한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 모델을 두는 곳(‘DATA_DIR/models/whisper’). 사용자의 HuggingFace 캐시를 쓰지 않는다 —
# 앱이 받은 것을 앱이 관리해야 지울 때도 한 곳만 보면 된다.
MODEL_DIR_NAME = "whisper"


@dataclass(frozen=True, slots=True)
class TranscribeModel:
    """전사 모델 하나.

    ``speed_hint``는 "영상 길이의 몇 배가 걸리는가"가 아니라 그 **역수**다 —
    10분 영상에 `realtime_ratio=0.1`이면 약 1분이 걸린다는 뜻이다. 사용자에게는
    `estimate_text()`로 시간으로 바꿔 보여준다.
    """

    key: str
    name: str
    disk_mb: int
    realtime_ratio: float
    note: str

    def estimate_sec(self, media_duration_sec: float) -> float:
        return max(0.0, media_duration_sec) * self.realtime_ratio

    def estimate_text(self, media_duration_sec: float) -> str:
        """이 모델로 이 영상을 전사하면 대략 얼마나 걸리는지."""
        seconds = self.estimate_sec(media_duration_sec)
        if seconds < 60:
            return "1분 미만"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"약 {minutes}분"
        hours, rem = divmod(minutes, 60)
        return f"약 {hours}시간 {rem}분"


# CPU(int8) 기준 대략치. 정확한 값은 기기마다 다르지만, **고를 때 필요한 것은
# 상대적인 크기 차이**라 보수적으로 잡았다.
MODELS: tuple[TranscribeModel, ...] = (
    TranscribeModel(
        key="tiny",
        name="가장 빠름 (tiny)",
        disk_mb=75,
        realtime_ratio=0.06,
        note="빠르지만 정확도가 낮습니다. 무슨 말인지 훑어볼 때.",
    ),
    TranscribeModel(
        key="base",
        name="권장 (base)",
        disk_mb=145,
        realtime_ratio=0.12,
        note="속도와 정확도가 무난합니다. 대부분 이걸로 충분합니다.",
    ),
    TranscribeModel(
        key="small",
        name="정확함 (small)",
        disk_mb=484,
        realtime_ratio=0.35,
        note="느리지만 정확합니다. 저사양 PC에서는 오래 걸립니다.",
    ),
)

MODELS_BY_KEY: dict[str, TranscribeModel] = {m.key: m for m in MODELS}

DEFAULT_MODEL_KEY = "base"


def find_model(key: str) -> TranscribeModel | None:
    return MODELS_BY_KEY.get(key)


def resolve_model(key: str) -> TranscribeModel:
    """설정 값 → 모델. 알 수 없으면 기본값으로 되돌린다.

    설정 파일이 손으로 고쳐지거나 모델 목록이 바뀌어도 기능이 죽지 않아야 한다.
    """
    return MODELS_BY_KEY.get(key) or MODELS_BY_KEY[DEFAULT_MODEL_KEY]


def segments_to_cues(segments) -> list[tuple[int, int, str]]:
    """전사 결과 → 자막 큐 `(시작ms, 끝ms, 텍스트)`.

    **빈 텍스트와 거꾸로 된 구간은 버린다.** 음성 인식은 무음 구간에서 빈 문자열이나
    길이 0짜리 조각을 내놓는데, 그대로 색인하면 검색 결과에 빈 줄이 섞인다.
    """
    cues: list[tuple[int, int, str]] = []
    for seg in segments or []:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        start_ms = int(max(0.0, float(getattr(seg, "start", 0.0))) * 1000)
        end_ms = int(max(0.0, float(getattr(seg, "end", 0.0))) * 1000)
        if end_ms <= start_ms:
            continue
        cues.append((start_ms, end_ms, text))
    return cues
