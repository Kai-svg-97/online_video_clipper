"""DetailInfoMixin — 상세화면의 info 영역.

    VideoDetailWidget에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다).
"""

from __future__ import annotations

import html
import logging
import re
from uuid import UUID

from PyQt6.QtCore import (
    QTimer,
    Qt,
    QUrl,
)
from PyQt6.QtGui import (
    QDesktopServices,
    QFont,
    QFontMetrics,
)
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


from gui.widgets.lyrics_overlay import LyricsTrack


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
    _BOLD2_RE,
    _BOLD_RE,
    _BULLET_RE,
    _HEADING_RE,
    _ITALIC_RE,
    _NUMBERED_RE,
    _TS_RE,
    _URL_RE,
)

logger = logging.getLogger(__name__)


class DetailInfoMixin:
    """제목·메타·태그·설명·메모 영역과 마크다운/타임스탬프 렌더링."""

    def _build_info(
        self,
        *,
        title: str,
        channel: str,
        duration_sec: int | None,
        published_at: str | None,
        view_count: int | None,
        favorite: bool,
        watched: bool,
        description: str | None,
        tags: list[str],
        tag_ids: dict[str, UUID],
        allow_tag_edit: bool,
    ) -> None:
        _clear_layout(self._meta_layout)

        # 제목은 플레이어 아래 고정 행(_title_lbl)에 표시
        self._title_lbl.setText(title)

        # ── 제목 아래 메타 행: 채널 · 조회수 · 등록일 · 재생시간 (+ 상태) ──
        meta_parts = []
        if channel:
            meta_parts.append(channel)
        if view_count is not None:
            meta_parts.append(f"조회수 {view_count:,}회")
        if published_at:
            meta_parts.append(published_at)
        if duration_sec is not None:
            meta_parts.append(_fmt_dur(duration_sec))
        if meta_parts:
            meta_lbl = QLabel("  ·  ".join(meta_parts))
            meta_lbl.setWordWrap(True)
            meta_lbl.setStyleSheet(f"color:{_t().text_secondary};")
            self._meta_layout.addWidget(meta_lbl)

        statuses = []
        if watched:
            statuses.append("✓ 시청완료")
        if favorite:
            statuses.append("★ 즐겨찾기")
        if statuses:
            st_lbl = QLabel("  ".join(statuses))
            st_lbl.setStyleSheet(f"color:{_t().text_muted};")
            self._meta_layout.addWidget(st_lbl)

        # ── "설명" 탭 내용: 태그 · 설명 (영속 위젯을 갱신) ──
        # 태그 — 글자 길이만큼의 칩이 폭에 맞춰 줄바꿈. 최대 3줄까지만 보이고 그 이상은
        # 스크롤(3줄 미만이면 내용 높이에 맞춤).
        _clear_layout(self._tags_holder_layout)
        has_tags = bool(tags)
        self._tags_header.setVisible(has_tags)
        self._tags_scroll.setVisible(has_tags)
        if has_tags:
            flow = _TagFlow(tags, tag_ids)
            flow.tag_clicked.connect(self.tag_filter_requested.emit)
            self._tags_holder_layout.addWidget(flow)
            f8 = QFont()
            f8.setPointSize(8)
            row_h = QFontMetrics(f8).height() + 12   # 칩 한 줄 대략 높이
            self._fit_tags_scroll(flow, row_h * 3 + 8)   # 최대 3줄

        # 수동 태그 추가 (로컬 영상만)
        _clear_layout(self._tag_add_layout)
        self._tag_add_input = None
        self._tag_add_container.setVisible(allow_tag_edit)
        if allow_tag_edit:
            self._tag_add_input = QLineEdit()
            self._tag_add_input.setPlaceholderText("태그 추가... (쉼표로 구분)")
            self._tag_add_input.setStyleSheet("font-size:8pt;")
            self._tag_add_input.returnPressed.connect(self._on_add_tag)
            self._tag_add_layout.addWidget(self._tag_add_input, 1)
            add_btn = QPushButton("+")
            add_btn.setFixedSize(24, 24)
            add_btn.setStyleSheet("font-size:11pt; font-weight:bold;")
            add_btn.clicked.connect(self._on_add_tag)
            self._tag_add_layout.addWidget(add_btn)

        # 설명 — 마크다운 서식 + 타임스탬프 seek 링크 렌더링. 높이는 위 _AutoHeightBrowser가
        # 가용 공간을 최대로 활용해 자동 조절(스크롤 최소화). 별도 "챕터" 섹션은 설명 속
        # 타임라인과 중복되므로 설명 하나로 병합한다.
        has_desc = bool(description)
        self._desc_header.setVisible(has_desc)
        self._desc_view.setVisible(has_desc)
        if has_desc:
            self._desc_view.setHtml(self._render_timestamped_html(description))

    def _fit_tags_scroll(self, flow: QWidget, cap: int) -> None:
        """태그 스크롤 높이를 내용(flow) 높이에 맞추되 최대 ``cap``(3줄)로 제한."""
        def _apply() -> None:
            try:
                w = self._tags_scroll.viewport().width()
                fh = (
                    flow.layout().heightForWidth(w)
                    if w > 4 else flow.sizeHint().height()
                )
            except RuntimeError:
                return
            self._tags_scroll.setFixedHeight(min(max(fh + 4, 26), cap))

        _apply()
        # 최초 표시 시 viewport 폭이 확정된 뒤 한 번 더 맞춘다.
        QTimer.singleShot(0, _apply)

    def _render_timestamped_html(self, text: str, line_gap: int = 0) -> str:
        """요약/설명 텍스트를 마크다운 서식 + 링크가 적용된 HTML로 렌더링한다.

        - `# `~`###### ` → 제목, `**굵게**`/`__굵게__` → 굵게, `*기울임*` → 기울임
        - `- `/`* `/`• `/`· ` → 불릿, `1.`/`1)` → 번호 목록, 선행 공백 → 들여쓰기
        - `MM:SS`·`HH:MM:SS` → `seek:` 링크, URL → 링크
          (`_on_summary_anchor_clicked`가 seek는 재생 위치 이동, URL은 브라우저로 라우팅)

        `line_gap`(px): 줄마다 하단 여백을 줘 단락·개행 간격을 넓힌다. 설명은 원문에
        빈 줄 단락 구분이 있어 0(조밀)로 충분하지만, Gemini 요약은 개행이 촘촘한
        연속 항목이라 값을 줘 읽기 편하게 벌린다.
        """
        if not text:
            return ""
        accent = _t().accent
        gap = max(0, line_gap)
        mb = f" margin-bottom:{gap}px;" if gap else ""

        def _link(m: re.Match) -> str:
            h = int(m.group(1)) if m.group(1) else 0
            sec = h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            return (
                f'<a href="seek:{sec}" style="color:{accent}; '
                f'text-decoration:none; font-weight:bold;">{m.group(0)}</a>'
            )

        def _emphasis(escaped: str) -> str:
            # escape된 텍스트에 굵게/기울임/타임스탬프 서식을 적용(순서 중요:
            # **/__ 먼저 소비 후 남은 * 를 기울임 처리, 마지막에 타임스탬프 링크).
            escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
            escaped = _BOLD2_RE.sub(r"<b>\1</b>", escaped)
            escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
            return _TS_RE.sub(_link, escaped)

        def _inline(seg: str) -> str:
            # URL은 escape/emphasis 전에 분리해 링크로 보존, 나머지 구간만 서식 적용.
            out: list[str] = []
            pos = 0
            for m in _URL_RE.finditer(seg):
                out.append(_emphasis(html.escape(seg[pos:m.start()])))
                url = m.group(0)
                out.append(
                    f'<a href="{html.escape(url, quote=True)}" '
                    f'style="color:{accent};">{html.escape(url)}</a>'
                )
                pos = m.end()
            out.append(_emphasis(html.escape(seg[pos:])))
            return "".join(out)

        def _render_line(line: str) -> str:
            stripped = line.lstrip(" \t")
            if not stripped:
                return f'<div style="font-size:{4 + gap}pt;">&nbsp;</div>'   # 빈 줄 간격
            indent = len(line) - len(stripped)
            base = sum(4 if c == "\t" else 1 for c in line[:indent]) * 7  # 들여쓰기 px

            hm = _HEADING_RE.match(stripped)
            if hm:
                size = {1: "13pt", 2: "12pt", 3: "11pt"}.get(len(hm.group(1)), "10pt")
                return (
                    f'<div style="margin:{6 + gap}px 0 {max(2, gap)}px {base}px; '
                    f'font-weight:bold; font-size:{size};">{_inline(hm.group(2))}</div>'
                )
            bm = _BULLET_RE.match(stripped)
            if bm:
                return (
                    f'<div style="margin-left:{base + 14}px;{mb}">'
                    f'•&nbsp;{_inline(bm.group(2))}</div>'
                )
            nm = _NUMBERED_RE.match(stripped)
            if nm:
                return (
                    f'<div style="margin-left:{base + 16}px;{mb}">'
                    f'{nm.group(1)}.&nbsp;{_inline(nm.group(2))}</div>'
                )
            if base:
                return f'<div style="margin-left:{base}px;{mb}">{_inline(stripped)}</div>'
            return f'<div style="{mb}">{_inline(stripped)}</div>' if mb else f"<div>{_inline(stripped)}</div>"

        return "".join(_render_line(line) for line in text.splitlines())

    def _set_crumb_path(self, path: list[tuple] | None) -> None:
        """브레드크럼 바를 path[(이름, category_id), ...]로 재구성한다."""
        while self._crumb_layout.count():
            item = self._crumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not path:
            self._crumb_bar.setVisible(False)
            return
        for i, (name, cat_id) in enumerate(path):
            if i > 0:
                sep = QLabel(" ›")
                sep.setStyleSheet(f"color:{_t().text_secondary}; font-size:9pt;")
                self._crumb_layout.addWidget(sep)
            btn = QPushButton(name)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { color:#5a9fd4; font-size:9pt; border:none; padding:0;"
                " text-decoration:underline; background:transparent; }"
                " QPushButton:hover { color:#8dc4f0; }"
            )
            btn.clicked.connect(lambda _, cid=cat_id: self.category_path_clicked.emit(cid))
            self._crumb_layout.addWidget(btn)
        self._crumb_layout.addStretch()
        self._crumb_bar.setVisible(True)

    def _on_notes_changed(self) -> None:
        if not self._streaming and self._detail is not None:
            self._notes_timer.start()

    def _save_notes(self) -> None:
        if self._detail is None or self._streaming:
            return
        self.notes_saved.emit(self._detail.id, self._notes_edit.toPlainText())

    def _on_add_tag(self) -> None:
        if self._tag_add_input is None or self._detail is None:
            return
        text = self._tag_add_input.text().strip()
        if not text:
            return
        new_names = [
            t.strip().lstrip("#")
            for part in text.split(",")
            for t in part.split()
            if t.strip().lstrip("#")
        ]
        if not new_names:
            return
        merged = list(dict.fromkeys(list(self._detail.tags) + new_names))
        self.tags_updated.emit(self._detail.id, merged)
        self._tag_add_input.clear()

    def _on_open_browser(self) -> None:
        if self._current_url:
            QDesktopServices.openUrl(QUrl(self._current_url))

    def _on_refresh_detail(self) -> None:
        """제목행 ⟳ — 현재 상세 정보를 부모에 재조회 요청(제자리 갱신)."""
        if self._detail is not None and not self._streaming:
            self.detail_refresh_requested.emit(self._detail.id)

    # ── 노래 탭 (외부=LibraryPanel/SongViewModel이 데이터 주입) ─────────
    def set_song_info(self, dto) -> None:
        """SongViewModel이 로드/갱신한 노래 정보를 노래 탭과 플레이어 자막에 반영한다."""
        self._song_tab.set_info(dto)
        # 스트리밍은 안정적 video_id가 없어 편집·자막 대상이 아니다.
        if dto is None or self._streaming or not dto.is_synced:
            self._player.set_lyrics(None)
            return
        self._player.set_lyrics(
            LyricsTrack.from_lines(dto.lyrics_lines, offset_ms=dto.lyrics_offset_ms)
        )

    def _on_subtitle_offset_changed(self, offset_ms: int) -> None:
        # video_id를 지금(변경 시점) 캡처한다 — 500ms 뒤 flush 시 self._detail이
        # 이미 다음 영상(자동재생 등)으로 바뀌어 있을 수 있어, 그때 self._detail.id를
        # 읽으면 A에서 조정한 값이 B에 저장되는 사고가 난다. load()/load_stream()에서
        # 타이머를 멈추는 방식(대안)은 사용자가 방금 조정한 값을 버리게 되므로 채택하지
        # 않았다 — A에서 조정한 값은 화면이 넘어갔어도 A에 저장돼야 한다는 것이 결론이다.
        self._song_tab.set_offset_ms(offset_ms)
        if self._detail is None or self._streaming:
            return
        self._pending_offset = (self._detail.id, offset_ms)
        self._offset_timer.start()
