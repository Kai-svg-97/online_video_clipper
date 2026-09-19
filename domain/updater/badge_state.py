"""업데이트 배지가 무엇을 보여 줄지 — **순수 판정**, Qt도 네트워크도 모른다.

배지 하나가 다섯 가지 일을 한다: 새 버전이 있다고 알리고, 어느 버전인지 보여 주고,
내려받는 진행률을 보여 주고, 설치할 준비가 됐음을 알리고, 실패하면 다시 누르게 한다.
그 판단을 위젯 안에 두면 화면을 띄워야만 검증할 수 있는데, **`paintEvent` 안에서 난
예외는 로그도 없이 프로세스를 죽인다**(0xC0000409). 그래서 계산은 전부 여기서 끝내고
위젯은 결과를 그리기만 한다.

## 왜 진행률을 되돌리지 않나

다운로드는 이어받기를 한다(`infrastructure/updater/update_checker.py`). 재시도가 걸리면
`downloaded`가 잠깐 0으로 돌아올 수 있는데, 그대로 그리면 배지가 깜빡인다. 사용자에게
그건 "고장"으로 읽히므로 **본 적 있는 최대값**만 반영한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# 배지에 적는 버전 문자열의 최대 길이. 넘으면 줄인다 — 프리릴리스 태그가 붙으면
# (`1.30.0-rc1`) 띠 안에서 폭이 무너진다.
MAX_VERSION_CHARS = 14

_MB = 1024 * 1024


class BadgeState(Enum):
    """배지가 취할 수 있는 상태. 순서가 곧 진행 순서다."""

    HIDDEN = "hidden"            # 새 버전 없음 — 배지를 숨긴다
    FOUND = "found"              # 발견 — 아직 받지 않았다
    DOWNLOADING = "downloading"  # 받는 중
    READY = "ready"              # 다 받았다 — 누르면 설치
    INSTALLING = "installing"    # 설치 착수 — 곧 앱이 닫힌다
    FAILED = "failed"            # 받다가 실패 — 누르면 재시도


class ClickAction(Enum):
    """배지를 눌렀을 때 할 일."""

    NOTHING = "nothing"
    DOWNLOAD = "download"
    INSTALL = "install"


@dataclass(frozen=True, slots=True)
class BadgeView:
    """화면이 읽는 값 묶음 — 위젯은 이것만 보고 그린다."""

    visible: bool
    label: str
    tooltip: str
    fill: float          # 0.0~1.0 — 진행률 채움 비율
    indeterminate: bool  # 총량을 모른다(채움 대신 다른 표시)
    action: ClickAction


def short_version(version: str) -> str:
    """배지에 적을 버전 문자열 — 너무 길면 줄인다."""
    v = (version or "").strip()
    if len(v) <= MAX_VERSION_CHARS:
        return v
    return v[: MAX_VERSION_CHARS - 1] + "…"


def progress_fraction(downloaded: int, total: int) -> float:
    """0.0~1.0 채움 비율.

    `total`이 0이면(Content-Length 없음) 비율을 만들 수 없다 — **0으로 나누지 않는다.**
    `downloaded`가 `total`을 넘는 경우도 있다(이어받기 뒤 서버가 Range를 무시하면
    받은 양이 전체보다 커 보인다) — 1.0으로 자른다.
    """
    if total <= 0:
        return 0.0
    if downloaded <= 0:
        return 0.0
    return min(1.0, downloaded / total)


def _mb(n: int) -> str:
    return f"{n / _MB:.1f}MB"


def describe(
    state: BadgeState,
    *,
    current_version: str = "",
    new_version: str = "",
    downloaded: int = 0,
    total: int = 0,
    size_bytes: int = 0,
    error: str = "",
) -> BadgeView:
    """상태를 화면이 읽을 값으로 바꾼다.

    `size_bytes`는 릴리스가 알려 준 자산 크기(`UpdateDTO.size_bytes`)이고, `total`은
    실제 응답의 Content-Length다. 받기 전에도 크기를 알려 주려고 둘을 따로 받는다.
    """
    short = short_version(new_version)

    if state is BadgeState.HIDDEN or not short:
        return BadgeView(
            visible=False, label="", tooltip="", fill=0.0,
            indeterminate=False, action=ClickAction.NOTHING,
        )

    if state is BadgeState.FOUND:
        size = f" ({_mb(size_bytes)})" if size_bytes > 0 else ""
        return BadgeView(
            visible=True,
            label=f"⭳ v{short}",
            tooltip=(
                f"현재 v{current_version} → v{new_version} 으로 업데이트됩니다{size}\n"
                "눌러서 내려받기"
            ),
            fill=0.0,
            indeterminate=False,
            action=ClickAction.DOWNLOAD,
        )

    if state is BadgeState.DOWNLOADING:
        if total <= 0:
            # 총량을 모르면 백분율이 거짓말이 된다 — 받은 양만 정직하게 보여 준다.
            return BadgeView(
                visible=True,
                label=f"v{short} · {_mb(downloaded)}",
                tooltip=f"내려받는 중… {_mb(downloaded)}",
                fill=0.0,
                indeterminate=True,
                action=ClickAction.NOTHING,
            )
        frac = progress_fraction(downloaded, total)
        return BadgeView(
            visible=True,
            label=f"v{short} · {int(frac * 100)}%",
            tooltip=f"내려받는 중… {_mb(downloaded)} / {_mb(total)}",
            fill=frac,
            indeterminate=False,
            action=ClickAction.NOTHING,
        )

    if state is BadgeState.READY:
        return BadgeView(
            visible=True,
            label=f"✓ v{short} 설치",
            tooltip=(
                f"v{new_version} 설치를 시작합니다\n"
                "앱이 닫히고 자동으로 다시 시작됩니다"
            ),
            fill=1.0,
            indeterminate=False,
            action=ClickAction.INSTALL,
        )

    if state is BadgeState.INSTALLING:
        return BadgeView(
            visible=True,
            label="설치 중…",
            tooltip="잠시 후 자동으로 다시 시작됩니다",
            fill=1.0,
            indeterminate=False,
            action=ClickAction.NOTHING,
        )

    # FAILED — 왜 실패했는지 말해 주지 않으면 사용자가 할 수 있는 일이 없다.
    reason = (error or "알 수 없는 오류").strip()
    return BadgeView(
        visible=True,
        label=f"⟳ v{short}",
        tooltip=f"내려받지 못했습니다: {reason}\n눌러서 다시 시도",
        fill=0.0,
        indeterminate=False,
        action=ClickAction.DOWNLOAD,
    )
