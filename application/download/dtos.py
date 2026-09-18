from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class DownloadProgressDTO:
    """화면으로 나가는 진행 상황.

    **도메인의 `DownloadProgress`와 같은 것을 담아야 한다.** 라이브 방송은 총량을
    몰라 퍼센트가 성립하지 않고, 화면은 `is_indeterminate`로 갈라 경과 시간·받은
    용량을 대신 보여준다. 이 DTO에 그 세 값이 빠져 있던 동안 **다운로드 카드를
    그리는 순간 앱이 죽었다** — `paint()` 안에서 난 AttributeError를 PyQt가
    프로세스 종료로 처리한다(0xC0000409). 필드를 늘릴 때 여기도 같이 늘린다.
    """

    percent: float = 0.0
    speed_bps: float = 0.0
    eta_sec: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0        # 0 = 모름(라이브)
    elapsed_sec: float = 0.0

    @property
    def is_indeterminate(self) -> bool:
        """총량을 모르는가 — 퍼센트를 보여줄 수 없는 상태."""
        return self.total_bytes <= 0

    def speed_formatted(self) -> str:
        if self.speed_bps < 1024:
            return f"{self.speed_bps:.0f} B/s"
        if self.speed_bps < 1_048_576:
            return f"{self.speed_bps / 1024:.1f} KB/s"
        return f"{self.speed_bps / 1_048_576:.1f} MB/s"


@dataclass(frozen=True)
class DownloadJobDTO:
    id: UUID
    url: str
    title: str
    status: str
    progress: DownloadProgressDTO = field(default_factory=DownloadProgressDTO)
    file_path: str | None = None
    error_msg: str | None = None
