"""SummaryTabMixin — 상세화면의 summary 영역.

    VideoDetailWidget에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    Qt,
    QUrl,
)
from PyQt6.QtWidgets import QPushButton
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
from gui.text import active_language, tr
from gui.text.catalog import AVAILABLE_LANGUAGES, language_name

logger = logging.getLogger(__name__)


def summary_generation_lang() -> str:
    """⟳ 가 요약을 만드는 언어 = 앱 언어(모르는 언어면 한국어).

    조립 루트(`bootstrap.services.summary_language`)의 자동 요약과 **같은 규칙**이어야
    한다 — 둘이 다르면 자동으로 받은 요약과 ⟳ 로 받은 요약이 다른 칸에 들어간다.
    그래서 둘 다 "요약 추출기가 아는 언어"를 기준으로 삼는다. 화면 언어만 늘리고
    추출기에 그 언어가 없으면, 그 언어 칸에 한국어 요약이 들어가는 대신 한국어로 받는다.
    """
    from infrastructure.browser.gemini_extractor import (  # noqa: PLC0415
        supported_summary_languages,
    )

    lang = active_language()
    return lang if lang in supported_summary_languages() else "ko"


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
            self._summary_status_lbl.setText(tr("영상을 먼저 선택해 주세요."))
            return
        if self._streaming:
            logger.info(
                "요약 추출 요청을 무시한다 — 라이브러리 밖(스트리밍) 영상: %s",
                self._detail.url,
            )
            self._summary_status_lbl.setText(
                tr("라이브러리에 담아야 요약을 만들 수 있습니다.")
            )
            return
        if self._gemini_worker is not None:
            logger.info("요약 추출이 이미 진행 중이다 — 중복 요청 무시")
            self._summary_status_lbl.setText(tr("이미 추출 중입니다…"))
            return
        logger.info("요약 추출 시작: %s", self._detail.url)
        self._summary_refresh_btn.setEnabled(False)
        self._summary_status_lbl.setText(tr("추출 중…"))
        # 요약 추출은 수십 초 걸린다 — 그 사이 화면이 정리돼도 스레드가 파괴되지 않게.
        #
        # **`deleteLater`를 걸지 않는다.** 예전에는 `finished`에 걸어 뒀는데, 그러면
        # 끝나는 순간 C++ 객체가 사라지면서 (1) 여기 `self._gemini_worker`가 죽은
        # 껍데기를 들고 있게 되고 (2) `gui/workers.py`의 레지스트리에도 죽은 객체가
        # 남아 **종료 시 `wait_all()`이 거기서 터졌다**. 참조만 놓으면 마지막 참조가
        # 사라질 때 파이썬이 정리한다(CLAUDE.md의 워커 수명 규칙).
        worker = track_thread(
            _GeminiSummaryWorker(self._detail.url, self._detail.id, summary_generation_lang())
        )
        worker.done.connect(self._on_gemini_done)
        worker.start()
        self._gemini_worker = worker

    def _on_gemini_done(self, video_id, lang: str, summary: str, reason: str = "") -> None:
        # 다 썼으니 레지스트리에서 놓아 준다 — 안 놓으면 종료할 때마다 끝난 워커를
        # 계속 기다린다. 신호는 **이름으로** 넘긴다(객체를 꺼내는 순간 터질 수 있다).
        retire_thread(self._gemini_worker, "done")
        self._gemini_worker = None
        # 요청 시점의 영상과 현재 표시 중인 영상이 다르면(사용자가 다른 영상으로
        # 이동) 화면은 건드리지 않는다. 단, 유효한 요약은 원래 요청 영상 id로
        # 저장해 데이터 정합을 유지한다.
        is_current = self._detail is not None and video_id == self._detail.id
        status = "" if summary else (reason or "error")
        if summary:
            self.gemini_summary_saved.emit(video_id, lang, summary)
        # 실패 사유(또는 성공 시 "")를 저장해 다음에 상세를 열 때도 이유가 보이게 한다.
        self.summary_status_saved.emit(video_id, lang, status)
        if not is_current:
            return
        self._summary_refresh_btn.setEnabled(True)
        if summary:
            # 편집 중이었다면 먼저 저장한다 — 화면을 바꾸면 편집기의 글이 버려진다.
            self._commit_summary_edit()
            self._summaries[lang] = summary
            self._summary_statuses.pop(lang, None)
            self._summary_stack.setCurrentWidget(self._summary_edit)
            self._show_summary_lang(lang)      # 받은 언어로 넘어가 보여 준다
            self._summary_status_lbl.setText("")
        else:
            self._summary_statuses[lang] = status
            if self._summary_lang == lang:
                self._summary_edit.setPlaceholderText(summary_placeholder(status))
            self._summary_status_lbl.setText(summary_failure_status_label(status))

    # ── 언어별 요약 ───────────────────────────────────────────────
    def _load_summaries(self, detail) -> None:
        """상세를 열 때 — 앱 언어의 요약을 먼저, 없으면 있는 다른 언어를 보여 준다."""
        self._summaries = dict(getattr(detail, "summaries", None) or {})
        self._summary_statuses = dict(getattr(detail, "summary_statuses", None) or {})
        gen = summary_generation_lang()
        if gen in self._summaries:
            lang = gen
        else:
            others = [c for c, _ in AVAILABLE_LANGUAGES if c in self._summaries]
            lang = others[0] if others else gen
        self._show_summary_lang(lang)

    def _show_summary_lang(self, lang: str) -> None:
        """`lang` 언어의 요약을 표시한다. 편집하면 이 언어로 저장된다."""
        self._summary_lang = lang
        self._summary_raw = self._summaries.get(lang, "")
        # 요약이 비어 있을 때 왜 없는지 알려준다(그 언어의 저장된 실패 사유 기준).
        self._summary_edit.setPlaceholderText(
            summary_placeholder(self._summary_statuses.get(lang, ""))
        )
        self._summary_edit.setHtml(
            self._render_timestamped_html(self._summary_raw, line_gap=self._SUMMARY_LINE_GAP)
        )
        gen = summary_generation_lang()
        if lang != gen and gen not in self._summaries:
            # 앱 언어 요약이 없어 다른 언어를 보여 주는 중 — 왜 이 언어인지 말한다.
            self._summary_status_lbl.setText(
                tr("{lang} 요약은 아직 없습니다 — ⟳ 로 만듭니다").format(
                    lang=language_name(gen)
                )
            )
        else:
            self._summary_status_lbl.setText("")
        self._refresh_summary_lang_chips()

    def _refresh_summary_lang_chips(self) -> None:
        """언어 칩을 다시 만든다 — **다른 언어의 요약이 있을 때만** 보인다.

        요약이 앱 언어 하나뿐이면 칩은 소음이다. 칩에는 요약이 있는 언어와 앱 언어만
        올린다(요약도 없고 ⟳ 로 만들 수도 없는 언어를 누르면 빈 화면만 나온다).
        선택된 칩은 **굵은 글씨**로만 구분한다 — 색을 칠하지 않으므로 테마를 바꿔도
        다시 칠할 것이 없다.
        """
        gen = summary_generation_lang()
        _clear_layout(self._summary_lang_layout)
        langs = [c for c, _ in AVAILABLE_LANGUAGES if c in self._summaries or c == gen]
        visible = any(c != gen for c in self._summaries)
        self._summary_lang_bar.setVisible(visible)
        self._summary_refresh_btn.setToolTip(
            tr("Gemini 요약 갱신 — {lang}로 만듭니다").format(lang=language_name(gen))
        )
        if not visible:
            return
        for code in langs:
            btn = QPushButton(language_name(code))
            btn.setFlat(True)
            btn.setCheckable(True)
            btn.setChecked(code == self._summary_lang)
            font = btn.font()
            font.setBold(code == self._summary_lang)
            btn.setFont(font)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("summary_lang", code)
            btn.clicked.connect(self._on_summary_lang_chip)
            self._summary_lang_layout.addWidget(btn)

    def _on_summary_lang_chip(self) -> None:
        btn = self.sender()
        code = btn.property("summary_lang") if btn is not None else None
        if not code:
            return
        # 편집 중이면 먼저 저장한다 — 언어를 바꾸면 편집 대상이 바뀐다.
        self._commit_summary_edit()
        self._show_summary_lang(str(code))

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
                # **보고 있는 언어**로 저장한다 — 영어 화면에서 한국어 요약을 고칠 수도 있다.
                lang = self._summary_lang or summary_generation_lang()
                if text:
                    self._summaries[lang] = text
                else:
                    self._summaries.pop(lang, None)
                self.gemini_summary_saved.emit(self._detail.id, lang, text)
                self._refresh_summary_lang_chips()
