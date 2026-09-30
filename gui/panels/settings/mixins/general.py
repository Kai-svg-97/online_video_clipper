"""GeneralSectionMixin — 설정 화면 윗부분 — 도움말·앱 언어·테마·저장 경로·일반·알림 섹션.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
)

from gui.panels.settings.helpers import _t, open_folder
from gui.panels.settings.theme_cards import _ThemeCard
from gui.text import tr
from gui.themes.tokens import PRESETS

logger = logging.getLogger(__name__)


class GeneralSectionMixin:
    """설정 화면 윗부분 — 도움말·앱 언어·테마·저장 경로·일반·알림 섹션."""

    def _build_help_section(self, layout) -> None:
        """도움말 — 상세 설명서로 가는 길. F1과 같은 곳을 연다.

        설정은 "어디서 찾지?"를 가장 먼저 열어 보는 화면이라 맨 위에 둔다.
        """
        label = QLabel(tr("도움말"))
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 8px;"
        )
        layout.addWidget(label)
        hint = QLabel(
            tr(
                "화면별 사용법과 화면 갈무리를 담은 상세 설명서를 기본 브라우저로 엽니다. "
                "어느 화면에서든 F1 을 눌러도 같은 문서가 열립니다."
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)
        button = QPushButton(tr("상세 설명서 열기  (F1)"))
        button.setToolTip(tr("상세 설명서를 기본 브라우저로 엽니다 (F1)"))
        button.clicked.connect(self._open_manual)
        layout.addWidget(button)
        layout.addSpacing(4)

    def _open_manual(self) -> None:
        from gui.help import open_manual  # noqa: PLC0415

        open_manual()

    def _build_language_section(self, layout) -> None:
        """화면 언어.

        **"앱 언어"라고 분명히 적는다.** 이 화면에는 언어 설정이 이미 둘 더 있다 —
        다운로드용 "자막 언어"와 재생 화면의 자막 트랙 선택. 그냥 "언어"라고 두면
        무엇을 바꾸는 항목인지 알 수 없다.
        """
        from config import settings as cfg  # noqa: PLC0415
        from gui.text.catalog import AVAILABLE_LANGUAGES  # noqa: PLC0415

        label = QLabel(tr("앱 언어"))
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 8px;"
        )
        layout.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._lang_combo = QComboBox()
        for code, name in AVAILABLE_LANGUAGES:
            self._lang_combo.addItem(name, code)
        idx = self._lang_combo.findData(cfg.UI_LANGUAGE)
        self._lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._lang_combo.setMinimumWidth(160)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        row.addWidget(self._lang_combo)
        row.addStretch()
        layout.addLayout(row)

        self._lang_hint = QLabel(
            tr("화면에 보이는 글의 언어입니다. 자막 파일 언어나 자막 번역 대상과는 다릅니다.")
        )
        self._lang_hint.setWordWrap(True)
        self._lang_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(self._lang_hint)
        layout.addSpacing(4)

    def _on_language_changed(self) -> None:
        """고른 언어를 저장한다 — **적용은 다시 시작할 때**.

        즉시 바꾸지 않는 이유: 이 앱의 위젯은 `setText()`로 생성 시점에 문자열을 박아
        넣으므로, 언어만 갈아 끼워도 이미 만들어진 화면은 그대로다. 되지도 않는
        즉시 전환을 흉내 내는 것보다 **언제 반영되는지 말해 주는** 편이 낫다.
        """
        from config import settings as cfg  # noqa: PLC0415

        code = self._lang_combo.currentData() or "ko"
        cfg.save_ui_language(code)
        self._lang_hint.setText(
            tr("다시 시작하면 적용됩니다. 번역이 없는 문구는 한국어로 남습니다.")
        )

    def _build_theme_section(self, layout) -> None:
        """테마 프리셋 격자."""
        # ── 테마 섹션 ──
        theme_label = QLabel(tr("테마"))
        theme_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(theme_label)
        layout.addSpacing(10)

        # 프리셋이 늘어 한 줄에 다 들어가지 않으므로 격자로 배치한다.
        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setHorizontalSpacing(16)
        cards_grid.setVerticalSpacing(14)
        per_row = 6
        for i, (name, tokens) in enumerate(PRESETS.items()):
            card = _ThemeCard(tokens)
            self._theme_cards[name] = card
            cards_grid.addWidget(card, i // per_row, i % per_row)
        cards_grid.setColumnStretch(per_row, 1)

        layout.addLayout(cards_grid)
        layout.addSpacing(8)

        hint = QLabel(tr("클릭하면 즉시 적용됩니다. 재시작 후에도 유지됩니다."))
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_muted}; margin-top: 4px;")
        layout.addWidget(hint)
        layout.addSpacing(28)

    def _build_paths_section(self, layout) -> None:
        """저장 경로(DB·다운로드·썸네일·로그) + 폴더 열기 버튼."""
        # ── 저장 경로 섹션 ──
        path_label = QLabel(tr("저장 경로"))
        path_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(path_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            paths = {
                tr("데이터베이스"): str(s.DATABASE_PATH),
                tr("다운로드 폴더"): str(s.DOWNLOAD_DIR),
                tr("썸네일 폴더"): str(s.THUMBNAIL_DIR),
                tr("로그 폴더"): str(s.LOG_DIR),
            }
        except Exception:
            logger.exception("설정 경로 로드 실패")
            paths = {}

        for label_text, path_text in paths.items():
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setMinimumWidth(90)
            lbl.setStyleSheet(f"font-size: 11px; color: {_t().text_muted};")
            val = QLabel(path_text)
            val.setStyleSheet(
                f"font-size: 10px; color: {_t().text_muted}; font-family: monospace;"
            )
            val.setWordWrap(False)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            open_btn = QPushButton(tr("열기"))
            # **고정 폭을 쓰지 않는다.** 한국어 "열기"에 맞춘 48px 에 영어 "Open"이
            # 들어가지 않아 글자가 잘렸다(실측). 번역된 글이 들어가는 위젯은 최소 폭만
            # 정하고 내용에 맞춰 늘어나게 둔다.
            open_btn.setMinimumWidth(48)
            open_btn.clicked.connect(lambda _checked=False, p=path_text: open_folder(p))
            row.addWidget(lbl)
            row.addWidget(val, 1)
            row.addWidget(open_btn)
            layout.addLayout(row)
            layout.addSpacing(6)

        note = QLabel(tr("경로를 변경하려면 data/config.yaml 을 편집하세요."))
        note.setStyleSheet(f"font-size: 10px; color: {_t().text_muted}; margin-top: 8px;")
        layout.addWidget(note)
        layout.addSpacing(28)

    def _build_general_section(self, layout) -> None:
        """일반 설정(테마 적용 방식·자동 보강 등)."""
        # ── 일반 섹션 ──
        gen_label = QLabel(tr("일반"))
        gen_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(gen_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            cur_concurrent = s.MAX_CONCURRENT_DOWNLOADS
            cur_feed_workers = s.MAX_CONCURRENT_FEED_WORKERS
            cur_clipboard = s.CLIPBOARD_MONITORING
            cur_auto_enrich = s.AUTO_ENRICH_ON_ADD
        except Exception:
            logger.exception("일반 설정 로드 실패")
            cur_concurrent = 3
            cur_feed_workers = 4
            cur_clipboard = True
            cur_auto_enrich = True

        # 동시 다운로드 수
        concurrent_row = QHBoxLayout()
        concurrent_row.setContentsMargins(0, 0, 0, 0)
        concurrent_lbl = QLabel(tr("동시 다운로드 수"))
        concurrent_lbl.setMinimumWidth(130)
        concurrent_lbl.setStyleSheet("font-size: 11px;")
        self._concurrent_spin = QSpinBox()
        self._concurrent_spin.setRange(1, 8)
        self._concurrent_spin.setValue(cur_concurrent)
        self._concurrent_spin.setFixedWidth(64)
        self._concurrent_spin.valueChanged.connect(self._on_concurrent_changed)
        concurrent_row.addWidget(concurrent_lbl)
        concurrent_row.addWidget(self._concurrent_spin)
        concurrent_row.addStretch()
        layout.addLayout(concurrent_row)
        layout.addSpacing(10)

        # 노드 동시 로딩 수 (피드·채널·카테고리·재생목록 등 모든 트리 노드 공통)
        feed_workers_row = QHBoxLayout()
        feed_workers_row.setContentsMargins(0, 0, 0, 0)
        feed_workers_lbl = QLabel(tr("노드 동시 로딩 수"))
        feed_workers_lbl.setMinimumWidth(130)
        feed_workers_lbl.setStyleSheet("font-size: 11px;")
        self._feed_workers_spin = QSpinBox()
        self._feed_workers_spin.setRange(1, 8)
        self._feed_workers_spin.setValue(cur_feed_workers)
        self._feed_workers_spin.setFixedWidth(64)
        self._feed_workers_spin.valueChanged.connect(self._on_feed_workers_changed)
        feed_workers_row.addWidget(feed_workers_lbl)
        feed_workers_row.addWidget(self._feed_workers_spin)
        feed_workers_row.addStretch()
        layout.addLayout(feed_workers_row)
        layout.addSpacing(10)

        # 클립보드 URL 자동 감지
        self._clipboard_check = QCheckBox(tr("클립보드 URL 자동 감지"))
        self._clipboard_check.setChecked(cur_clipboard)
        self._clipboard_check.checkStateChanged.connect(self._on_clipboard_changed)
        layout.addWidget(self._clipboard_check)
        layout.addSpacing(10)

        # 등록 시 요약·가사 자동 채우기
        self._auto_enrich_check = QCheckBox(tr("등록 시 요약·가사 자동 채우기"))
        self._auto_enrich_check.setChecked(cur_auto_enrich)
        self._auto_enrich_check.checkStateChanged.connect(self._on_auto_enrich_changed)
        layout.addWidget(self._auto_enrich_check)

        enrich_hint = QLabel(
            tr(
                "영상을 한 건씩 등록할 때 음원용 영상은 가사를, 그 외 영상은 Gemini 요약을 "
                "백그라운드에서 채웁니다. 재생목록·채널 일괄 가져오기는 대상이 아닙니다.\n"
                "요약은 YouTube 로그인 쿠키가 필요합니다 — Chrome 127 이상은 쿠키 자동 추출이 "
                "불가하므로 아래 인증 섹션에서 쿠키 파일을 직접 등록해야 합니다."
            )
        )
        enrich_hint.setWordWrap(True)
        enrich_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;")
        layout.addWidget(enrich_hint)

        self._build_notify_rows(layout)
        layout.addSpacing(28)

    # ── 알림 · 새 영상 감시 ───────────────────────────────────────

    def _build_notify_rows(self, layout) -> None:
        """트레이 알림과 구독 채널 새 영상 감시.

        다운로드는 몇 분~몇 시간이 걸린다. 그동안 사용자는 이 앱을 보고 있지 않아
        앱 안의 토스트로는 끝났다는 소식이 전달되지 않는다.
        """
        from config import settings as cfg  # noqa: PLC0415
        from domain.monitoring.watch import (  # noqa: PLC0415
            MAX_INTERVAL_MIN,
            MIN_INTERVAL_MIN,
            clamp_interval,
        )
        from gui.tray import AppTray  # noqa: PLC0415

        layout.addSpacing(10)
        self._tray_check = QCheckBox(tr("작업이 끝나면 트레이로 알리기"))
        self._tray_check.setChecked(bool(cfg.TRAY_NOTIFICATIONS))
        self._tray_check.checkStateChanged.connect(self._on_tray_notify_changed)
        layout.addWidget(self._tray_check)

        if not AppTray.is_available():
            # 트레이가 없는 데스크톱이 있다 — 켤 수 있게 두면 켜 놓고 안 온다고 한다.
            self._tray_check.setEnabled(False)
            self._tray_check.setToolTip(tr("이 환경에는 시스템 트레이가 없습니다."))

        self._watch_check = QCheckBox(tr("구독 채널에 새 영상이 올라오면 알리기"))
        self._watch_check.setChecked(bool(cfg.WATCH_NEW_VIDEOS))
        self._watch_check.checkStateChanged.connect(self._on_watch_changed)
        layout.addWidget(self._watch_check)

        int_row = QHBoxLayout()
        int_row.setContentsMargins(22, 0, 0, 0)
        int_lbl = QLabel(tr("확인 주기(분)"))
        int_lbl.setMinimumWidth(100)
        self._watch_spin = QSpinBox()
        self._watch_spin.setRange(MIN_INTERVAL_MIN, MAX_INTERVAL_MIN)
        self._watch_spin.setValue(clamp_interval(cfg.WATCH_INTERVAL_MIN))
        self._watch_spin.setFixedWidth(80)
        self._watch_spin.valueChanged.connect(self._on_watch_interval_changed)
        int_row.addWidget(int_lbl)
        int_row.addWidget(self._watch_spin)
        int_row.addStretch()
        layout.addLayout(int_row)

        hint = QLabel(
            tr(
                "확인은 배경에서 조용히 이뤄지며 보고 있는 목록을 건드리지 않습니다. "
                "너무 자주 확인하면 YouTube가 요청을 막을 수 있어 최소 "
                "{min}분입니다. 바꾼 주기는 앱을 다시 켤 때 적용됩니다."
            ).format(min=MIN_INTERVAL_MIN)
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;")
        layout.addWidget(hint)

    def _on_tray_notify_changed(self, _state) -> None:
        self._save_setting("tray_notifications", self._tray_check.isChecked())

    def _on_watch_changed(self, _state) -> None:
        self._save_setting("watch_new_videos", self._watch_check.isChecked())

    def _on_watch_interval_changed(self, value: int) -> None:
        from domain.monitoring.watch import clamp_interval  # noqa: PLC0415

        self._save_setting("watch_interval_min", clamp_interval(value))

    def _on_concurrent_changed(self, value: int) -> None:
        from config import settings as s
        s.save_setting("max_concurrent_downloads", value)

    def _on_feed_workers_changed(self, value: int) -> None:
        from config import settings as s
        s.save_setting("max_concurrent_feed_workers", value)
        self.feed_workers_changed.emit(value)

    def _on_clipboard_changed(self, state) -> None:
        from config import settings as s
        checked = (state == Qt.CheckState.Checked)
        s.save_setting("clipboard_monitoring", checked)

    def _on_auto_enrich_changed(self, state) -> None:
        from config import settings as s
        checked = (state == Qt.CheckState.Checked)
        s.save_setting("auto_enrich_on_add", checked)
