"""SummaryTabMixin — 상세화면의 summary 영역.

    VideoDetailWidget에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QUrl,
)
from PyQt6.QtGui import (
    QDesktopServices,
)


from gui.workers import retire_thread, track_thread


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

from gui.panels.detail.text_format import (
    summary_failure_status_label,
    summary_placeholder,
)

logger = logging.getLogger(__name__)


class SummaryTabMixin:
    """요약 탭 — Gemini 요약 표시/편집과 재추출."""

    def _on_summary_anchor_clicked(self, url: QUrl) -> None:
        """설명/요약 내 링크 클릭을 라우팅한다.

        `seek:` 링크는 재생 위치를 이동하고, http/https URL은 기본 브라우저로 연다.
        """
        s = url.toString()
        if s.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)
            return
        if not s.startswith("seek:"):
            return
        try:
            sec = int(s[len("seek:"):])
        except ValueError:
            return
        self._player.seek_to_ms(sec * 1000)
        if not self._player.is_playing():
            self._player.play()

    def _on_refresh_summary(self) -> None:
        """⟳ — Gemini 요약을 다시 추출한다.

        **아무 말 없이 돌아가지 않는다.** 예전에는 조건이 맞지 않으면 그냥 `return`
        했는데, 그러면 버튼을 눌러도 화면이 그대로여서 "기능이 죽었다"로 보이고
        로그에도 흔적이 없어 원인을 쫓을 수가 없었다(CLAUDE.md — 상태를 말하지 않는
        화면을 만들지 않는다).
        """
        if self._detail is None:
            logger.info("요약 추출 요청을 무시한다 — 표시 중인 영상이 없다")
            self._summary_status_lbl.setText("영상을 먼저 선택해 주세요.")
            return
        if self._streaming:
            logger.info(
                "요약 추출 요청을 무시한다 — 라이브러리 밖(스트리밍) 영상: %s",
                self._detail.url,
            )
            self._summary_status_lbl.setText(
                "라이브러리에 담아야 요약을 만들 수 있습니다."
            )
            return
        if self._gemini_worker is not None:
            logger.info("요약 추출이 이미 진행 중이다 — 중복 요청 무시")
            self._summary_status_lbl.setText("이미 추출 중입니다…")
            return
        logger.info("요약 추출 시작: %s", self._detail.url)
        self._summary_refresh_btn.setEnabled(False)
        self._summary_status_lbl.setText("추출 중…")
        # 요약 추출은 수십 초 걸린다 — 그 사이 화면이 정리돼도 스레드가 파괴되지 않게.
        #
        # **`deleteLater`를 걸지 않는다.** 예전에는 `finished`에 걸어 뒀는데, 그러면
        # 끝나는 순간 C++ 객체가 사라지면서 (1) 여기 `self._gemini_worker`가 죽은
        # 껍데기를 들고 있게 되고 (2) `gui/workers.py`의 레지스트리에도 죽은 객체가
        # 남아 **종료 시 `wait_all()`이 거기서 터졌다**. 참조만 놓으면 마지막 참조가
        # 사라질 때 파이썬이 정리한다(CLAUDE.md의 워커 수명 규칙).
        worker = track_thread(_GeminiSummaryWorker(self._detail.url, self._detail.id))
        worker.done.connect(self._on_gemini_done)
        worker.start()
        self._gemini_worker = worker

    def _on_gemini_done(self, video_id, summary: str, reason: str = "") -> None:
        # 다 썼으니 레지스트리에서 놓아 준다 — 안 놓으면 종료할 때마다 끝난 워커를
        # 계속 기다린다. 신호는 **이름으로** 넘긴다(객체를 꺼내는 순간 터질 수 있다).
        retire_thread(self._gemini_worker, "done")
        self._gemini_worker = None
        # 요청 시점의 영상과 현재 표시 중인 영상이 다르면(사용자가 다른 영상으로
        # 이동) 화면은 건드리지 않는다. 단, 유효한 요약은 원래 요청 영상 id로
        # 저장해 데이터 정합을 유지한다.
        is_current = self._detail is not None and video_id == self._detail.id
        if summary:
            self.gemini_summary_saved.emit(video_id, summary)
        # 실패 사유(또는 성공 시 "")를 저장해 다음에 상세를 열 때도 이유가 보이게 한다.
        self.summary_status_saved.emit(video_id, "" if summary else (reason or "error"))
        if not is_current:
            return
        if not summary:
            self._summary_edit.setPlaceholderText(summary_placeholder(reason or "error"))
        self._summary_refresh_btn.setEnabled(True)
        if summary:
            self._summary_raw = summary
            self._summary_edit.setHtml(
                self._render_timestamped_html(summary, line_gap=self._SUMMARY_LINE_GAP)
            )
            self._summary_stack.setCurrentWidget(self._summary_edit)
            self._summary_status_lbl.setText("")
        else:
            self._summary_status_lbl.setText(summary_failure_status_label(reason or "error"))

    def _enter_summary_edit(self) -> None:
        """요약 표시 영역 더블클릭 시 편집 모드로 전환한다(로컬 영상만)."""
        if self._streaming or self._detail is None:
            return
        self._summary_editor.setPlainText(self._summary_raw)
        self._summary_stack.setCurrentWidget(self._summary_editor)
        self._summary_editor.setFocus()

    def _commit_summary_edit(self) -> None:
        """편집 내용을 저장하고 표시 모드로 복귀한다.

        내용이 바뀌었으면 렌더링을 갱신하고 `gemini_summary_saved`로 영속화한다.
        """
        if self._summary_stack.currentWidget() is not self._summary_editor:
            return
        text = self._summary_editor.toPlainText()
        self._summary_stack.setCurrentWidget(self._summary_edit)
        if text != self._summary_raw:
            self._summary_raw = text
            self._summary_edit.setHtml(
                self._render_timestamped_html(text, line_gap=self._SUMMARY_LINE_GAP)
            )
            if self._detail is not None and not self._streaming:
                self.gemini_summary_saved.emit(self._detail.id, text)
