"""원본 영상이 아직 살아 있는지에 대한 **순수 규칙** — I/O 없음.

아카이브 용도로 모아 둔 라이브러리에서 가장 아픈 지점은 "담아 둔 영상이 원본에서
사라진 것"이다. 그런데 사라짐에도 종류가 있고, **대응이 서로 다르다**.

- `삭제됨` — 업로더가 내렸거나 YouTube가 지웠다. 다시 볼 방법이 없다.
- `비공개` — 아직 존재하지만 볼 수 없다. 나중에 다시 공개될 수 있으므로 지우자고
  권하면 안 된다.
- `확인 불가` — 네트워크 실패·미지원 사이트. **살아 있는 것으로 취급한다** —
  확인하지 못한 것을 '사라졌다'고 보고하면 멀쩡한 영상을 지우게 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_OK = "ok"
STATUS_REMOVED = "removed"
STATUS_PRIVATE = "private"
STATUS_UNKNOWN = "unknown"

# 화면에 보여줄 이름.
STATUS_LABELS: dict[str, str] = {
    STATUS_OK: "정상",
    STATUS_REMOVED: "삭제됨",
    STATUS_PRIVATE: "비공개",
    STATUS_UNKNOWN: "확인 불가",
}

# 사용자에게 "사라졌다"고 보고할 상태. `UNKNOWN`은 **포함하지 않는다**.
MISSING_STATUSES: frozenset[str] = frozenset({STATUS_REMOVED, STATUS_PRIVATE})


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    """영상 1건의 확인 결과."""

    status: str
    detail: str = ""

    @property
    def is_missing(self) -> bool:
        return self.status in MISSING_STATUSES

    @property
    def label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


def classify_http_status(code: int) -> AvailabilityResult:
    """oEmbed 응답 코드를 판정으로 바꾼다.

    YouTube oEmbed는 살아 있는 영상에 200, 내려간 영상에 404, 비공개 영상에 401을
    돌려준다. 그 밖의 코드(429 속도 제한, 5xx 장애)는 **영상의 문제가 아니므로**
    확인 불가로 둔다 — 서버가 잠깐 아픈 것을 두고 영상을 지우게 하면 안 된다.
    """
    if code == 200:
        return AvailabilityResult(STATUS_OK)
    if code == 404:
        return AvailabilityResult(STATUS_REMOVED, "원본이 삭제되었거나 주소가 바뀌었습니다")
    if code in (401, 403):
        return AvailabilityResult(STATUS_PRIVATE, "비공개로 바뀌어 볼 수 없습니다")
    return AvailabilityResult(STATUS_UNKNOWN, f"응답 코드 {code}")
