"""YouTubeAccountMixin — YouTube API 연동 섹션 — 번들 OAuth 로그인·연결 해제·상태 표시.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from gui.panels.settings.helpers import _t
from gui.text import tr
from gui.themes.colors import sem
from gui.workers import track_thread

logger = logging.getLogger(__name__)


class YouTubeAccountMixin:
    """YouTube API 연동 섹션 — 번들 OAuth 로그인·연결 해제·상태 표시."""

    def _build_youtube_api_section(self, layout) -> None:
        """YouTube API 연동(번들 OAuth 로그인)."""
        # ── YouTube API 연동 섹션 ──
        layout.addSpacing(20)
        yt_label = QLabel(tr("YouTube API 연동"))
        yt_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(yt_label)
        layout.addSpacing(10)

        yt_desc = QLabel(
            tr(
                "Google 계정을 연결하면 YouTube 재생목록 동기화(읽기·쓰기)와\n"
                "구독 채널 가져오기를 사용할 수 있습니다.\n"
                "로그인은 기본 브라우저의 Google 페이지에서 안전하게 진행됩니다."
            )
        )
        yt_desc.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
        yt_desc.setWordWrap(True)
        layout.addWidget(yt_desc)
        layout.addSpacing(8)

        yt_btn_row = QHBoxLayout()
        self._yt_auth_btn = QPushButton(tr("Google 계정으로 연결"))
        self._yt_auth_btn.setMinimumWidth(160)
        self._yt_auth_btn.clicked.connect(self._on_yt_auth)
        yt_btn_row.addWidget(self._yt_auth_btn)

        self._yt_disconnect_btn = QPushButton(tr("연결 해제"))
        self._yt_disconnect_btn.setMinimumWidth(80)
        self._yt_disconnect_btn.clicked.connect(self._on_yt_disconnect)
        yt_btn_row.addWidget(self._yt_disconnect_btn)
        yt_btn_row.addStretch()
        layout.addLayout(yt_btn_row)
        layout.addSpacing(6)

        self._yt_status_lbl = QLabel()
        self._yt_status_lbl.setWordWrap(True)
        layout.addWidget(self._yt_status_lbl)
        self._refresh_yt_status()

    # ── YouTube API OAuth ──────────────────────────────────────────────────

    @staticmethod
    def _yt_btn_disconnected() -> str:
        return tr("Google 계정으로 연결")

    @staticmethod
    def _yt_btn_working() -> str:
        return tr("연결 중…")

    @staticmethod
    def _yt_btn_connected() -> str:
        return tr("Google 계정 다시 연결")

    def _refresh_yt_status(self) -> None:
        if self._yt_oauth is None:
            self._yt_status_lbl.setText(tr("○ YouTube API 미초기화"))
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
            self._yt_auth_btn.setEnabled(False)
            return
        if not self._yt_oauth.has_client_config():
            self._yt_status_lbl.setText(
                tr("YouTube OAuth 설정이 앱에 포함되지 않았습니다. 배포자에게 문의하세요.")
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('warning')};")
            self._yt_auth_btn.setEnabled(False)
            self._yt_auth_btn.setText(self._yt_btn_disconnected())
            return
        self._yt_auth_btn.setEnabled(True)
        if self._yt_oauth.is_authenticated():
            name = self._yt_oauth.get_channel_name() or tr("인증됨")
            self._yt_status_lbl.setText(
                tr(
                    "● 연결됨: {name}\n앱을 다시 시작하면 모든 YouTube 연동 기능이 활성화됩니다."
                ).format(name=name)
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('success')};")
            self._yt_auth_btn.setText(self._yt_btn_connected())
        else:
            self._yt_status_lbl.setText(tr("○ 미연결 — Google 계정으로 연결하세요"))
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('danger')};")
            self._yt_auth_btn.setText(self._yt_btn_disconnected())

    def _on_yt_auth(self) -> None:
        if self._yt_oauth is None or not self._yt_oauth.has_client_config():
            return

        from PyQt6.QtCore import QThread, pyqtSignal as _sig  # noqa: PLC0415

        class _AuthWorker(QThread):
            done = _sig(str)   # channel_name or ""
            err  = _sig(str)

            def __init__(self, oauth, parent=None):
                super().__init__(parent)
                self._oauth = oauth

            def run(self):
                try:
                    self._oauth.run_auth_flow()
                    name = self._oauth.get_channel_name() or tr("인증됨")
                    self.done.emit(name)
                except Exception as exc:
                    logger.exception("YouTube OAuth 인증 실패")
                    # 설정 오류는 `DisplayError`로 온다 — 문장은 화면 언어로 만든다.
                    from gui.text.messages import describe_error  # noqa: PLC0415

                    self.err.emit(describe_error(exc))

        self._yt_auth_btn.setEnabled(False)
        self._yt_auth_btn.setText(self._yt_btn_working())
        self._yt_status_lbl.setText(tr("브라우저에서 Google 계정으로 승인하세요…"))
        self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")

        # 인증 창이 떠 있는 동안 설정 화면을 떠나도 스레드가 파괴되지 않게 등록한다.
        worker = track_thread(_AuthWorker(self._yt_oauth))

        def _on_done(name: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText(self._yt_btn_connected())
            self._yt_status_lbl.setText(
                tr(
                    "● 연결됨: {name}\n앱을 다시 시작하면 모든 YouTube 연동 기능이 활성화됩니다."
                ).format(name=name)
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('success')};")
            self._yt_auth_worker = None

        def _on_err(msg: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText(self._yt_btn_disconnected())
            self._yt_status_lbl.setText(tr("연결 실패: {msg}").format(msg=msg[:120]))
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('danger')};")
            self._yt_auth_worker = None

        worker.done.connect(_on_done)
        worker.err.connect(_on_err)
        self._yt_auth_worker = worker
        worker.start()

    def _on_yt_disconnect(self) -> None:
        if self._yt_oauth is None:
            return
        self._yt_oauth.clear()
        self._refresh_yt_status()
