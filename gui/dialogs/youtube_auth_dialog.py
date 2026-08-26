"""YouTube 통합 인증 다이얼로그."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from config.settings import DATA_DIR
from infrastructure.auth.youtube_auth import YouTubeAuthService, write_netscape_cookies
from gui.themes.colors import sem, tok

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 백그라운드 워커들
# ---------------------------------------------------------------------------

class _LoginStatusWorker(QThread):
    finished = pyqtSignal(object)  # str | None

    def __init__(self, auth_service: YouTubeAuthService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._auth = auth_service

    def run(self) -> None:
        self.finished.emit(self._auth.check_login_status())


def _find_system_chromium_exe() -> str | None:
    """시스템에 설치된 Chrome / Edge 실행 파일 경로를 반환한다."""
    import os
    import shutil

    if sys.platform == "win32":
        lad  = os.environ.get("LOCALAPPDATA", "")
        pf   = os.environ.get("PROGRAMFILES", "")
        pf86 = os.environ.get("PROGRAMFILES(X86)", "")
        candidates = [
            Path(pf)   / "Google/Chrome/Application/chrome.exe",
            Path(pf86) / "Google/Chrome/Application/chrome.exe",
            Path(lad)  / "Google/Chrome/Application/chrome.exe",
            Path(pf86) / "Microsoft/Edge/Application/msedge.exe",
            Path(pf)   / "Microsoft/Edge/Application/msedge.exe",
            Path(pf)   / "BraveSoftware/Brave-Browser/Application/brave.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    elif sys.platform == "darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
        for c in candidates:
            if c.exists():
                return str(c)

    return (
        shutil.which("google-chrome")
        or shutil.which("chromium-browser")
        or shutil.which("chromium")
    )


class _PlaywrightLoginWorker(QThread):
    login_success  = pyqtSignal(str)   # cookie_file_path
    login_failed   = pyqtSignal(str)   # error message
    browser_opened = pyqtSignal()      # 시스템 브라우저를 열었을 때 (playwright 없음)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        cookie_path = DATA_DIR / "auth" / "youtube_cookies.txt"

        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError:
            self._open_system_browser()
            return

        exe = _find_system_chromium_exe()

        try:
            with sync_playwright() as p:
                kwargs: dict = {
                    "headless": False,
                    # Google은 자동화 도구로 제어되는 브라우저의 로그인을 적극적으로
                    # 차단한다("로그인할 수 없음 — 브라우저 또는 앱이 안전하지
                    # 않을 수 있습니다"). navigator.webdriver 노출을 없애면 일부
                    # 판정을 완화할 수 있다(gemini_extractor.py와 동일한 조치).
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if exe:
                    kwargs["executable_path"] = exe
                browser = p.chromium.launch(**kwargs)
                try:
                    context = browser.new_context()
                    context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', "
                        "{get: () => undefined});"
                    )
                    page = context.new_page()
                    page.goto(
                        "https://accounts.google.com/signin/v2/identifier?service=youtube",
                        timeout=30_000,
                    )
                    # 로그인 완료 후 YouTube 메인으로 리디렉션될 때까지 대기 (최대 5분)
                    page.wait_for_url("*://www.youtube.com/**", timeout=300_000)
                    cookies = context.cookies("https://www.youtube.com")
                    write_netscape_cookies(cookie_path, cookies)
                finally:
                    # 타임아웃·사용자 취소 등 예외 시에도 브라우저 프로세스를
                    # 반드시 종료해 좀비 chromium이 남지 않게 한다.
                    try:
                        browser.close()
                    except Exception:
                        logger.exception("playwright 브라우저 종료 실패")
            self.login_success.emit(str(cookie_path))
        except Exception as exc:
            error = str(exc)
            # playwright 번들 chromium 누락 + 시스템 브라우저도 없는 경우
            if exe is None and ("executable" in error.lower() or "not found" in error.lower()):
                self._open_system_browser()
            else:
                self.login_failed.emit(error)

    def _open_system_browser(self) -> None:
        import webbrowser  # noqa: PLC0415
        webbrowser.open("https://accounts.google.com/signin/v2/identifier?service=youtube")
        self.browser_opened.emit()


# ---------------------------------------------------------------------------
# 메인 다이얼로그
# ---------------------------------------------------------------------------

class YouTubeAuthDialog(QDialog):
    """YouTube 계정 통합 인증 다이얼로그.

    브라우저 프로필 선택, 쿠키 파일 직접 지정, Playwright 로그인 세 가지 방식 제공.
    """

    auth_changed = pyqtSignal()   # 인증 설정이 저장될 때 발생

    def __init__(
        self,
        auth_service: YouTubeAuthService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._auth = auth_service
        self._status_worker: _LoginStatusWorker | None = None
        self._login_worker: _PlaywrightLoginWorker | None = None

        self.setWindowTitle("YouTube 계정 연동")
        self.setMinimumWidth(460)
        self.setMinimumHeight(380)

        self._build_ui()
        self._load_current_settings()
        self._check_status()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 상태 배너 — YouTube 채널명 표시
        self._status_banner = QLabel("상태 확인 중…")
        self._status_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_banner.setFixedHeight(44)
        self._status_banner.setStyleSheet(
            f"background: {tok().bg_elevated}; border: 1px solid {tok().border_muted};"
            f" border-radius: 6px; color: {tok().text_secondary}; font-size: 10pt;"
        )
        root.addWidget(self._status_banner)

        # 탭
        tabs = QTabWidget()
        tabs.addTab(self._build_browser_tab(), "브라우저 계정")
        tabs.addTab(self._build_cookiefile_tab(), "쿠키 파일")
        root.addWidget(tabs, 1)

        # 하단 버튼 행
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._login_btn = QPushButton("새 계정으로 로그인…")
        self._login_btn.setToolTip(
            "아직 브라우저에 YouTube 로그인이 안 된 경우에만 사용하세요.\n"
            "시스템 브라우저(Chrome/Edge)를 열어 Google 로그인 후 쿠키를 저장합니다.\n"
            "이미 Firefox / Chrome에 로그인되어 있다면 위의 '브라우저 계정' 탭에서\n"
            "프로필을 클릭하기만 하면 됩니다."
        )
        self._login_btn.clicked.connect(self._on_browser_login)
        btn_row.addWidget(self._login_btn)

        self._logout_btn = QPushButton("로그아웃")
        self._logout_btn.clicked.connect(self._on_logout)
        btn_row.addWidget(self._logout_btn)

        btn_row.addStretch()

        self._close_btn = QPushButton("닫기")
        self._close_btn.setDefault(True)
        self._close_btn.clicked.connect(self._on_close)
        btn_row.addWidget(self._close_btn)

        root.addLayout(btn_row)

        self._progress_lbl = QLabel("")
        self._progress_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_lbl.setStyleSheet(f"font-size: 9pt; color: {tok().text_secondary};")
        root.addWidget(self._progress_lbl)

    def _build_browser_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 브라우저 선택
        browser_row = QHBoxLayout()
        browser_row.addWidget(QLabel("브라우저:"))
        self._browser_combo = QComboBox()
        self._browser_combo.addItems(["firefox", "chrome", "edge", "chromium"])
        self._browser_combo.setFixedWidth(120)
        self._browser_combo.currentTextChanged.connect(self._on_browser_changed)
        browser_row.addWidget(self._browser_combo)
        browser_row.addStretch()
        layout.addLayout(browser_row)

        # 안내 메시지
        guide = QLabel(
            "브라우저에서 YouTube에 로그인된 Google 계정을 선택하세요.\n"
            "Chrome은 이메일, Firefox는 프로필명이 표시됩니다."
        )
        guide.setWordWrap(True)
        guide.setStyleSheet(
            f"font-size: 9pt; color: {tok().text_secondary}; "
            f"background: {tok().bg_elevated}; border: 1px solid {tok().border_muted};"
            " border-radius: 4px; padding: 6px;"
        )
        layout.addWidget(guide)

        # 계정 목록
        profile_lbl = QLabel("Google 계정 / 브라우저 프로필:")
        profile_lbl.setStyleSheet(
            f"font-size: 9pt; color: {tok().text_secondary}; font-weight: 600;"
        )
        layout.addWidget(profile_lbl)

        self._profile_list = QListWidget()
        self._profile_list.setMinimumHeight(100)
        self._profile_list.itemClicked.connect(self._on_profile_selected)
        layout.addWidget(self._profile_list, 1)

        self._chrome_warn = QLabel(
            "⚠ Chrome은 실행 중일 때 쿠키 DB가 잠겨 오류가 납니다.\n"
            "Chrome을 닫거나 Firefox를 선택하세요."
        )
        self._chrome_warn.setWordWrap(True)
        self._chrome_warn.setStyleSheet(
            f"font-size: 8pt; color: {sem('warning')}; "
            f"background: {tok().bg_elevated}; border: 1px solid {sem('warning')};"
            " border-radius: 4px; padding: 4px;"
        )
        self._chrome_warn.hide()
        layout.addWidget(self._chrome_warn)

        hint = QLabel("계정 클릭 → 선택 저장 → 상단에서 연결된 YouTube 채널 확인")
        hint.setStyleSheet(f"font-size: 8pt; color: {tok().text_secondary};")
        layout.addWidget(hint)

        return w

    def _build_cookiefile_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        desc = QLabel(
            "Netscape 포맷 쿠키 파일 경로를 직접 지정합니다.\n"
            "브라우저 확장 프로그램(예: Get cookies.txt LOCALLY)으로 내보낸 파일을 사용하세요."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 9pt; color: {tok().text_secondary};")
        layout.addWidget(desc)

        file_row = QHBoxLayout()
        self._cookie_file_edit = QLineEdit()
        self._cookie_file_edit.setPlaceholderText("쿠키 파일 경로 (예: C:\\cookies.txt)")
        file_row.addWidget(self._cookie_file_edit, 1)
        browse_btn = QPushButton("찾기…")
        browse_btn.setFixedWidth(56)
        browse_btn.clicked.connect(self._on_browse_cookie)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        apply_btn = QPushButton("이 파일로 설정")
        apply_btn.clicked.connect(self._on_apply_cookiefile)
        layout.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addStretch()
        return w

    # ------------------------------------------------------------------
    # 현재 설정 로드

    def _load_current_settings(self) -> None:
        import config.settings as s  # noqa: PLC0415
        browser = getattr(s, "YT_AUTH_BROWSER", "chrome") or "chrome"
        idx = self._browser_combo.findText(browser)
        if idx >= 0:
            self._browser_combo.setCurrentIndex(idx)
        cookiefile = getattr(s, "YT_AUTH_COOKIEFILE", None)
        if cookiefile:
            self._cookie_file_edit.setText(cookiefile)
        self._refresh_profiles(browser)
        # 현재 선택된 프로필 강조
        profile = getattr(s, "YT_AUTH_PROFILE", None)
        if profile:
            for i in range(self._profile_list.count()):
                item = self._profile_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == profile:
                    self._profile_list.setCurrentItem(item)
                    break

    # ------------------------------------------------------------------
    # 프로필 목록 갱신

    def _refresh_profiles(self, browser: str) -> None:
        self._profile_list.clear()
        profiles = self._auth.detect_profiles(browser)
        if not profiles:
            empty = QListWidgetItem("프로필을 찾을 수 없습니다.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._profile_list.addItem(empty)
            return
        for p in profiles:
            item = QListWidgetItem(p.display_name)
            item.setData(Qt.ItemDataRole.UserRole, p.profile_key)
            self._profile_list.addItem(item)

    # ------------------------------------------------------------------
    # 로그인 상태 확인

    def _check_status(self) -> None:
        self._status_banner.setText("상태 확인 중…")
        self._status_banner.setStyleSheet(
            f"background: {tok().bg_elevated}; border: 1px solid {tok().border_muted};"
            f" border-radius: 6px; color: {tok().text_secondary}; font-size: 10pt;"
        )
        if self._status_worker and self._status_worker.isRunning():
            return
        self._status_worker = _LoginStatusWorker(self._auth, self)
        self._status_worker.finished.connect(self._on_status_result)
        self._status_worker.start()

    def _on_status_result(self, account_name: object) -> None:
        name = account_name  # str | None
        if name:
            self._status_banner.setText(
                f"● 연결된 YouTube 채널:  {name}\n"
                "구독 채널 / 재생목록 / 피드가 이 계정 기준으로 동작합니다."
            )
            self._status_banner.setStyleSheet(
                f"background: {tok().bg_elevated}; border: 1px solid {sem('success')};"
                f" border-radius: 6px; color: {sem('success')}; "
                "font-size: 10pt; font-weight: 600; padding: 4px;"
            )
        else:
            self._status_banner.setText(
                "○ YouTube 연결 없음  —  아래에서 계정을 선택하세요\n"
                "구독 채널·재생목록 기능을 사용하려면 연결이 필요합니다."
            )
            self._status_banner.setStyleSheet(
                f"background: {tok().bg_elevated}; border: 1px solid {sem('danger')};"
                f" border-radius: 6px; color: {sem('danger')}; "
                "font-size: 9pt; padding: 4px;"
            )

    # ------------------------------------------------------------------
    # 이벤트 핸들러

    def _on_browser_changed(self, browser: str) -> None:
        self._refresh_profiles(browser)
        self._chrome_warn.setVisible(browser in ("chrome", "chromium", "edge"))

    def _on_profile_selected(self, item: QListWidgetItem) -> None:
        profile_key = item.data(Qt.ItemDataRole.UserRole)
        if not profile_key:
            return
        browser = self._browser_combo.currentText()
        self._auth.save_auth(browser=browser, profile_key=profile_key, cookiefile=None)
        self._progress_lbl.setText(f"'{item.text()}' 계정으로 설정되었습니다.")
        self.auth_changed.emit()
        self._check_status()

    def _on_browse_cookie(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "쿠키 파일 선택", "", "텍스트 파일 (*.txt);;모든 파일 (*)"
        )
        if path:
            self._cookie_file_edit.setText(path)

    def _on_apply_cookiefile(self) -> None:
        cookiefile = self._cookie_file_edit.text().strip()
        if not cookiefile:
            self._progress_lbl.setText("쿠키 파일 경로를 입력하세요.")
            return
        browser = self._browser_combo.currentText()
        self._auth.save_auth(browser=browser, profile_key=None, cookiefile=cookiefile)
        self._progress_lbl.setText("쿠키 파일이 설정되었습니다.")
        self.auth_changed.emit()
        self._check_status()

    def _on_browser_login(self) -> None:
        if self._login_worker and self._login_worker.isRunning():
            return
        self._login_btn.setEnabled(False)
        self._login_btn.setText("브라우저 열리는 중…")
        self._progress_lbl.setText(
            "Chromium 창에서 Google 계정으로 로그인한 후 YouTube로 이동하면 자동 완료됩니다."
        )
        self._login_worker = _PlaywrightLoginWorker(self)
        self._login_worker.login_success.connect(self._on_login_success)
        self._login_worker.login_failed.connect(self._on_login_failed)
        self._login_worker.browser_opened.connect(self._on_browser_opened)
        self._login_worker.start()

    def _on_login_success(self, cookie_path: str) -> None:
        self._login_btn.setEnabled(True)
        self._login_btn.setText("브라우저로 로그인")
        browser = self._browser_combo.currentText()
        self._auth.save_auth(browser=browser, profile_key=None, cookiefile=cookie_path)
        self._cookie_file_edit.setText(cookie_path)
        self._progress_lbl.setText("로그인 완료! 쿠키 파일이 저장되었습니다.")
        self.auth_changed.emit()
        self._check_status()

    def _on_browser_opened(self) -> None:
        self._login_btn.setEnabled(True)
        self._login_btn.setText("브라우저로 로그인")
        self._progress_lbl.setText(
            "시스템 브라우저를 열었습니다. YouTube에 로그인한 후 "
            "위의 '브라우저 계정' 탭에서 프로필을 선택하세요."
        )

    def _on_login_failed(self, error: str) -> None:
        self._login_btn.setEnabled(True)
        self._login_btn.setText("브라우저로 로그인")
        self._progress_lbl.setText(f"로그인 실패: {error[:100]}")

    def _on_logout(self) -> None:
        self._auth.clear_auth()
        self._profile_list.clearSelection()
        self._cookie_file_edit.clear()
        self._progress_lbl.setText("로그아웃되었습니다.")
        self.auth_changed.emit()
        self._on_status_result(None)

    def _on_close(self) -> None:
        self.accept()
