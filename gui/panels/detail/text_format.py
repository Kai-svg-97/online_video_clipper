"""설명·요약 렌더링 규칙(마크다운·타임스탬프·URL 정규식)과 요약 실패 안내 문구.

렌더러(상세화면 info mixin)와 화면 문구를 같은 곳에 둔다 — 문구만 바꾸려고 위젯
코드를 열지 않아도 되게.
"""

from __future__ import annotations

import logging
import re





# ── 상세화면 동작 묶음 (gui/panels/detail/mixins/*) ────────────────
# 화면 뼈대(_setup_skeleton)와 로드 진입점만 이 파일에 남기고, 탭별 동작은
# 주제별 mixin으로 나눴다. 런타임 클래스는 하나라 상태 공유는 이전과 같다.

# ── 분할된 부품 (gui/panels/detail/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.panels.detail.widgets import (  # noqa: F401
    _AutoHeightBrowser,
    _AutoHeightPlainEdit,
    _DblClickLabel,
    _EditableField,
    _FlowLayout,
    _LockedNotice,
    _SpinRefreshButton,
    _TagChip,
    _TagFlow,
    _bold_font,
    _clear_layout,
    _fmt_size,
    _hline,
    _open_file,
    _open_folder,
    _t,
    _wrap,
)
from gui.panels.detail.related import (  # noqa: F401
    RelatedItem,
    _RelatedList,
    _RelatedRow,
    _fmt_dur,
    _fmt_pub,
    _payload_key,
)
from gui.panels.detail.song_tab import (  # noqa: F401
    _LyricRow,
    _LyricsCandidateList,
    _SongTab,
    _candidate_tooltip,
)
from gui.panels.detail.workers import (  # noqa: F401
    _GeminiSummaryWorker,
)

logger = logging.getLogger(__name__)


# 설명·요약의 타임스탬프(MM:SS / HH:MM:SS)를 seek 링크로 변환할 때 쓰는 정규식.
_TS_RE = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})")

# 설명·요약 속 URL을 클릭 가능한 링크로 변환할 때 쓰는 정규식.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

# 마크다운 서식 렌더링용 정규식(설명·요약 공통).
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")          # **굵게**

_BOLD2_RE = re.compile(r"__(.+?)__")             # __굵게__

_ITALIC_RE = re.compile(r"\*(?!\s)(.+?)(?<!\s)\*")  # *기울임*

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")   # # 제목

_BULLET_RE = re.compile(r"^([-*•·])\s+(.*)$")    # 불릿 목록

_NUMBERED_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")  # 번호 목록

# 요약 탭 안내 문구 — 실패 사유(SUMMARY_REASON_*)별로 다르게 보여준다.
# "질문하기 버튼이 없어서"는 사용자가 손쓸 수 없는 YouTube 측 제약이므로
# 쿠키·네트워크 문제와 반드시 구분해야 한다(그냥 "요약이 없습니다"로 두면
# 사용자가 설정을 계속 확인하게 된다).
_SUMMARY_PLACEHOLDERS: dict[str, str] = {
    "": (
        "Gemini AI 요약이 없습니다.\n"
        "⟳ 버튼으로 갱신하거나 더블클릭하여 직접 입력하세요."
    ),
    "no_button": (
        "질문하기 버튼이 없어 가져오는데 실패했습니다.\n"
        "조회수가 적거나 최근 업로드된 영상은 YouTube가 요약 기능을 제공하지 않습니다. "
        "나중에 ⟳ 버튼으로 다시 시도하거나 더블클릭하여 직접 입력하세요."
    ),
    "not_signed_in": (
        "YouTube 로그인이 필요해 요약을 가져오지 못했습니다.\n"
        "설정에서 쿠키를 등록한 뒤 ⟳ 버튼으로 다시 시도하세요."
    ),
    "error": (
        "요약을 가져오는 중 오류가 발생했습니다.\n"
        "⟳ 버튼으로 다시 시도하거나 더블클릭하여 직접 입력하세요."
    ),
}

# 상태바(_summary_status_lbl)용 한 줄 요약 — 실패 사유와 무관하게 항상 같은 문구
# ("설정에서 브라우저/프로필을 선택하거나 쿠키 파일을 등록하세요")를 보여주면
# "no_button"(YouTube가 이 영상에 요약 기능을 제공하지 않음)처럼 설정을 만져도
# 소용없는 경우까지 설정을 고치라고 안내해 불필요한 시행착오를 유발한다.
_SUMMARY_STATUS_LABELS: dict[str, str] = {
    "no_button": "요약 추출 실패 — 이 영상은 YouTube가 요약 기능을 제공하지 않습니다",
    "not_signed_in": "요약 추출 실패 — 로그인된 브라우저를 찾지 못했습니다",
    "error": "요약 추출 실패 — 잠시 후 다시 시도하세요",
}

def summary_failure_status_label(reason: str) -> str:
    """요약 실패 사유에 맞는 한 줄 상태 문구를 반환한다(모르는 값은 error와 동일)."""
    return _SUMMARY_STATUS_LABELS.get(reason, _SUMMARY_STATUS_LABELS["error"])

def summary_placeholder(status: str) -> str:
    """요약 실패 사유에 맞는 안내 문구를 반환한다(모르는 값은 기본 문구)."""
    return _SUMMARY_PLACEHOLDERS.get(status or "", _SUMMARY_PLACEHOLDERS[""])
