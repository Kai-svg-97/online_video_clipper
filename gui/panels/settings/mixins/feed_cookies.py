"""FeedCookieMixin — 구독 피드용 브라우저 쿠키 섹션 — 브라우저 로그인·프로필·쿠키 파일·도움말.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from domain.shared.ports import (
    COOKIE_EMPTY,
    COOKIE_NOT_COOKIES,
    COOKIE_NOT_FOUND,
    COOKIE_OK,
)
from gui.panels.settings.helpers import _t, open_folder
from gui.text import tr
from gui.themes.colors import sem

logger = logging.getLogger(__name__)


# 쿠키 파일 등록 방법 안내 — "이건 컴퓨터 전문가용 앱이 아니다"는 사용자 신고에 따라,
# 브라우저 프로필 자동 감지가 전혀 동작하지 않는 환경(기업 보안 정책, 지원되지 않는
# 브라우저 등)에서도 일반 사용자가 이해할 수 있는 대체 경로를 안내한다.
def cookie_help_text() -> str:
    """쿠키 파일 등록 안내문 — 언어가 정해진 뒤에 만들도록 함수로 둔다."""
    return tr(
        "브라우저/프로필 자동 감지가 계속 실패한다면, 쿠키 파일을 직접 등록하는 "
        "방법이 가장 확실합니다.\n\n"
        "1. 사용 중인 브라우저의 웹 스토어에서 'Get cookies.txt LOCALLY' (또는 "
        "'cookies.txt') 확장 프로그램을 설치하세요.\n"
        "2. www.youtube.com 에 접속해 로그인되어 있는지 확인하세요.\n"
        "3. 확장 프로그램 아이콘을 클릭하고 '내보내기(Export)'를 눌러 쿠키 파일을 "
        "저장하세요. 특별히 지정하지 않으면 보통 다운로드 폴더에 저장됩니다.\n"
        "4. 이 설정 화면으로 돌아와 '다시 검색'을 누르면 저장한 파일이 "
        "'감지된 쿠키 파일' 목록에 나타납니다. 선택하면 끝입니다.\n\n"
        "문제가 계속되면 아래 '로그 폴더 열기'로 연 폴더의 app.log 파일을 함께 "
        "보내주세요."
    )


class FeedCookieMixin:
    """구독 피드용 브라우저 쿠키 섹션 — 브라우저 로그인·프로필·쿠키 파일·도움말."""

    def _build_cookie_section(self, layout) -> None:
        """구독 피드용 브라우저 쿠키(YouTube API에 피드 엔드포인트가 없다)."""
        # ── 구독 피드 브라우저 쿠키 (YouTube API에는 피드 엔드포인트 없음) ──
        layout.addSpacing(16)
        feed_label = QLabel(tr("구독 피드 — 브라우저 쿠키 (선택)"))
        feed_label.setStyleSheet(
            f"font-size: 9px; font-weight: 600; letter-spacing: 0.5px; color: {_t().text_secondary};"
        )
        layout.addWidget(feed_label)
        feed_hint = QLabel(
            tr(
                "YouTube API는 구독 피드(최신 영상 목록) 엔드포인트를 제공하지 않아\n"
                "브라우저 쿠키가 필요합니다. 가장 확실한 방법은 아래 '쿠키 파일 등록 "
                "방법 보기'입니다 — 평소 쓰던 브라우저로 직접 로그인한 뒤 내보내는 "
                "방식이라 항상 동작합니다."
            )
        )
        feed_hint.setWordWrap(True)
        feed_hint.setStyleSheet(f"font-size: 8pt; color: {_t().text_secondary};")
        layout.addWidget(feed_hint)
        layout.addSpacing(6)

        self._browser_login_btn = QPushButton(tr("브라우저 열어서 로그인"))
        self._browser_login_btn.setToolTip(
            tr(
                "이 앱이 직접 띄운 브라우저 창에서 로그인합니다. Google이 자동화된\n"
                "브라우저로 판단해 \"로그인할 수 없음\"으로 거부할 수 있습니다 —\n"
                "그런 경우 아래 '쿠키 파일 등록 방법 보기'를 이용하세요."
            )
        )
        self._browser_login_btn.clicked.connect(self._on_open_auth_dialog)
        layout.addWidget(self._browser_login_btn)
        layout.addSpacing(10)

        adv_label = QLabel(tr("고급: 기존 브라우저 프로필 직접 선택"))
        adv_label.setStyleSheet(f"font-size: 8pt; color: {_t().text_muted};")
        layout.addWidget(adv_label)

        browser_row = QHBoxLayout()
        b_lbl = QLabel(tr("브라우저"))
        b_lbl.setMinimumWidth(100)
        self._feed_browser_combo = QComboBox()
        self._feed_browser_combo.addItems(["firefox", "chrome", "edge", "chromium"])
        self._feed_browser_combo.setFixedWidth(120)
        self._feed_browser_combo.currentTextChanged.connect(self._on_feed_browser_changed)
        browser_row.addWidget(b_lbl)
        browser_row.addWidget(self._feed_browser_combo)
        browser_row.addStretch()
        layout.addLayout(browser_row)

        profile_row = QHBoxLayout()
        p_lbl = QLabel(tr("프로필"))
        p_lbl.setMinimumWidth(100)
        self._feed_profile_combo = QComboBox()
        self._feed_profile_combo.setMinimumWidth(220)
        self._feed_profile_combo.setToolTip(tr("브라우저 프로필을 선택하세요"))
        self._feed_profile_combo.currentIndexChanged.connect(self._on_feed_profile_changed)
        profile_row.addWidget(p_lbl)
        profile_row.addWidget(self._feed_profile_combo, 1)
        layout.addLayout(profile_row)

        cand_row = QHBoxLayout()
        cand_lbl = QLabel(tr("감지된 쿠키 파일"))
        cand_lbl.setMinimumWidth(100)
        self._feed_cookie_candidates_combo = QComboBox()
        self._feed_cookie_candidates_combo.setToolTip(
            tr(
                "다운로드·데스크톱 폴더에서 자동으로 찾은 쿠키 파일입니다. 선택하면 "
                "아래 경로란에 채워집니다."
            )
        )
        self._feed_cookie_candidates_combo.currentIndexChanged.connect(
            self._on_cookie_candidate_selected
        )
        cand_refresh = QPushButton(tr("다시 검색"))
        cand_refresh.setMinimumWidth(70)
        cand_refresh.clicked.connect(self._reload_cookie_candidates)
        cand_row.addWidget(cand_lbl)
        cand_row.addWidget(self._feed_cookie_candidates_combo, 1)
        cand_row.addWidget(cand_refresh)
        layout.addLayout(cand_row)

        cookie_row = QHBoxLayout()
        ck_lbl = QLabel(tr("또는 쿠키 파일"))
        ck_lbl.setMinimumWidth(100)
        self._feed_cookie_edit = QLineEdit()
        self._feed_cookie_edit.setPlaceholderText(tr("Netscape 포맷 쿠키 파일 경로 (선택)"))
        ck_browse = QPushButton(tr("찾기…"))
        ck_browse.setMinimumWidth(48)
        ck_browse.clicked.connect(self._on_browse_cookie_file)
        cookie_row.addWidget(ck_lbl)
        cookie_row.addWidget(self._feed_cookie_edit, 1)
        cookie_row.addWidget(ck_browse)
        layout.addLayout(cookie_row)

        ck_apply = QPushButton(tr("쿠키 파일 적용"))
        ck_apply.setMinimumWidth(110)
        ck_apply.clicked.connect(self._on_apply_cookie_file)
        layout.addWidget(ck_apply)

        help_row = QHBoxLayout()
        self._cookie_help_btn = QPushButton(tr("쿠키 파일 등록 방법 보기"))
        self._cookie_help_btn.setMinimumWidth(160)
        self._cookie_help_btn.clicked.connect(self._on_show_cookie_help)
        self._open_log_dir_btn = QPushButton(tr("로그 폴더 열기"))
        self._open_log_dir_btn.setMinimumWidth(100)
        self._open_log_dir_btn.clicked.connect(self._on_open_log_dir)
        help_row.addWidget(self._cookie_help_btn)
        help_row.addWidget(self._open_log_dir_btn)
        help_row.addStretch()
        layout.addLayout(help_row)

        self._feed_status_lbl = QLabel()
        self._feed_status_lbl.setWordWrap(True)
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {_t().text_secondary};")
        layout.addWidget(self._feed_status_lbl)
        self._refresh_feed_auth_ui()

    # ── 브라우저 쿠키 (구독 피드) ──────────────────────────────────────────────

    def _refresh_feed_auth_ui(self) -> None:
        """현재 저장된 브라우저 쿠키 설정을 UI에 반영한다."""
        try:
            import config.settings as s  # noqa: PLC0415
            browser = getattr(s, "YT_AUTH_BROWSER", "firefox") or "firefox"
            idx = self._feed_browser_combo.findText(browser)
            if idx >= 0:
                self._feed_browser_combo.setCurrentIndex(idx)
            self._reload_profiles(browser)
            cookiefile = getattr(s, "YT_AUTH_COOKIEFILE", None)
            if cookiefile:
                self._feed_cookie_edit.setText(cookiefile)
            profile = getattr(s, "YT_AUTH_PROFILE", None)
            self._feed_status_lbl.setText(self._cookie_status_text(
                profile, cookiefile, self._auth.cookie_file_state if self._auth else None
            ))
            self._reload_cookie_candidates()
        except Exception:
            logger.exception("브라우저 쿠키 설정 UI 반영 실패")

    @staticmethod
    def _cookie_status_text(
        profile: "str | None",
        cookiefile: "str | None",
        cookie_state: "Callable[[str], str] | None" = None,
    ) -> str:
        """지금 무엇으로 인증하는지 + **그게 쓸 수 있는 상태인지**.

        예전에는 경로만 적었다. 그래서 다른 PC에서 등록한 경로가 그대로 남아 있어도
        멀쩡해 보였고, 요약이 "로그인된 브라우저를 찾지 못했습니다"로 실패하는데
        설정 화면만 봐서는 원인을 알 수 없었다(실제 신고).

        `cookie_state`는 판정 함수(`IYouTubeAuth.cookie_file_state`)다. 없으면 판정할
        수 없으므로 경로만 보여 준다.
        """
        if cookiefile:
            state = cookie_state(cookiefile) if cookie_state else COOKIE_OK
            if state == COOKIE_OK:
                return tr("쿠키 파일: {path}").format(path=cookiefile)
            trouble = {
                COOKIE_NOT_FOUND: tr("이 경로에 파일이 없습니다(다른 PC에서 등록했거나 지워졌습니다)"),
                COOKIE_EMPTY: tr("파일이 비어 있습니다"),
                COOKIE_NOT_COOKIES: tr("쿠키 파일 형식이 아닙니다"),
            }.get(state, tr("쓸 수 없는 파일입니다"))
            return tr("⚠ 쿠키 파일을 쓸 수 없습니다 — {trouble}\n{path}").format(
                trouble=trouble, path=cookiefile
            )
        if profile:
            return tr("프로필: {profile}").format(profile=profile)
        return tr("미설정 — 로그인된 브라우저를 자동으로 찾습니다")

    def _reload_cookie_candidates(self) -> None:
        """다운로드·데스크톱 폴더에서 쿠키 파일 후보를 다시 스캔해 목록에 채운다."""
        self._feed_cookie_candidates_combo.blockSignals(True)
        self._feed_cookie_candidates_combo.clear()
        try:
            candidates = self._auth.find_cookie_file_candidates() if self._auth else []
        except Exception:
            logger.exception("쿠키 파일 후보 탐색 실패")
            candidates = []
        if candidates:
            self._feed_cookie_candidates_combo.addItem(tr("아래에서 선택하세요"), None)
            for path in candidates:
                self._feed_cookie_candidates_combo.addItem(
                    f"{path.name}  ({path.parent.name})", str(path)
                )
        else:
            self._feed_cookie_candidates_combo.addItem(
                tr("다운로드·데스크톱에서 찾지 못함 — 아래 '찾기…'로 직접 선택"), None
            )
        self._feed_cookie_candidates_combo.blockSignals(False)

    def _on_cookie_candidate_selected(self, _index: int) -> None:
        path = self._feed_cookie_candidates_combo.currentData()
        if not path:
            return
        self._feed_cookie_edit.setText(path)

    def _on_open_auth_dialog(self) -> None:
        """자체 브라우저 창을 띄워 로그인시키고 쿠키를 직접 캡처하는 다이얼로그를 연다.

        기존 브라우저의 쿠키 DB를 복사하지 않아(Chrome 잠금·App-Bound Encryption과
        무관) 자동 감지가 실패하는 환경에서도 동작한다. "쿠키를 왜 찾아야 하냐,
        브라우저를 띄워서 로그인시키면 안 되냐"는 사용자 요청으로 연결됨 —
        `YouTubeAuthDialog`는 이미 구현돼 있었지만 이 버튼이 생기기 전까지는
        앱 어디에서도 열리지 않는 코드였다.
        """
        if self._auth is None:
            logger.info("브라우저 로그인 요청을 무시한다 — 인증 서비스가 주입되지 않았다")
            return
        from gui.dialogs.youtube_auth_dialog import YouTubeAuthDialog  # noqa: PLC0415

        dialog = YouTubeAuthDialog(self._auth, self)
        dialog.auth_changed.connect(self._refresh_feed_auth_ui)
        dialog.exec()

    def _reload_profiles(self, browser: str) -> None:
        import config.settings as s  # noqa: PLC0415
        self._feed_profile_combo.blockSignals(True)
        self._feed_profile_combo.clear()
        self._feed_profile_combo.addItem(tr("(선택 안 함)"), None)
        try:
            profiles = self._auth.detect_profiles(browser) if self._auth else []
            for p in profiles:
                self._feed_profile_combo.addItem(p.display_name, p.profile_key)
            # 현재 저장된 프로필 선택
            saved = getattr(s, "YT_AUTH_PROFILE", None)
            if saved:
                for i in range(self._feed_profile_combo.count()):
                    if self._feed_profile_combo.itemData(i) == saved:
                        self._feed_profile_combo.setCurrentIndex(i)
                        break
        except Exception:
            logger.exception("브라우저 프로필 목록 로드 실패")
        finally:
            self._feed_profile_combo.blockSignals(False)

    def _on_feed_browser_changed(self, browser: str) -> None:
        self._reload_profiles(browser)

    def _on_feed_profile_changed(self, _index: int) -> None:
        profile_key = self._feed_profile_combo.currentData()
        if profile_key is None or self._auth is None:
            return
        browser = self._feed_browser_combo.currentText()
        self._auth.save_auth(browser=browser, profile_key=profile_key, cookiefile=None)
        self._feed_status_lbl.setText(
            tr("저장됨: {name}").format(name=self._feed_profile_combo.currentText())
        )
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {sem('success')};")

    def _on_browse_cookie_file(self) -> None:
        from PyQt6.QtWidgets import QFileDialog  # noqa: PLC0415
        path, _ = QFileDialog.getOpenFileName(
            self, tr("쿠키 파일 선택"), "", tr("텍스트 파일 (*.txt);;모든 파일 (*)")
        )
        if path:
            self._feed_cookie_edit.setText(path)

    def _on_apply_cookie_file(self) -> None:
        cookiefile = self._feed_cookie_edit.text().strip()
        if not cookiefile or self._auth is None:
            return
        browser = self._feed_browser_combo.currentText()
        self._auth.save_auth(browser=browser, profile_key=None, cookiefile=cookiefile)
        self._feed_status_lbl.setText(tr("쿠키 파일이 설정되었습니다."))
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {sem('success')};")

    def _on_show_cookie_help(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("쿠키 파일 등록 방법"))
        v = QVBoxLayout(dialog)
        text_lbl = QLabel(cookie_help_text())
        text_lbl.setWordWrap(True)
        v.addWidget(text_lbl)
        btn_row = QHBoxLayout()
        dl_btn = QPushButton(tr("다운로드 폴더 열기"))
        dl_btn.clicked.connect(lambda: open_folder(Path.home() / "Downloads"))
        close_btn = QPushButton(tr("닫기"))
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(dl_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)
        dialog.exec()

    def _on_open_log_dir(self) -> None:
        from config import settings as s  # noqa: PLC0415
        open_folder(s.LOG_DIR)
