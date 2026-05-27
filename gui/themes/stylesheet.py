"""전체 앱 QSS 빌더.

build_qss(tokens) 로 ThemeTokens를 완전한 Qt StyleSheet 문자열로 변환한다.
QApplication.instance().setStyleSheet(qss) 에 직접 적용된다.
"""
from __future__ import annotations

import dataclasses

from gui.themes.tokens import ThemeTokens

# ---------------------------------------------------------------------------
# QSS 템플릿 — {token_name} 자리표시자는 ThemeTokens 필드명과 일치
# ---------------------------------------------------------------------------
_QSS_TEMPLATE = """\
/* ====== 기반 ====== */
QWidget {{
    background-color: {bg_base};
    color: {text_primary};
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 12px;
    border: none;
    outline: none;
}}

QMainWindow, QDialog {{
    background-color: {bg_base};
}}

/* ====== 스크롤바 ====== */
QScrollBar:vertical {{
    background: {bg_surface};
    width: 6px;
    margin: 0;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {bg_overlay};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {text_muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {bg_surface};
    height: 6px;
    margin: 0;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {bg_overlay};
    border-radius: 3px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {text_muted};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ====== 입력 필드 ====== */
QLineEdit {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: {bg_overlay};
}}
QLineEdit:focus {{
    border: 1px solid {border_muted};
}}
QLineEdit:disabled {{
    color: {text_muted};
    border-color: {border};
}}

/* ====== 버튼 ====== */
QPushButton {{
    background-color: {bg_elevated};
    color: {text_secondary};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px 10px;
}}
QPushButton:hover {{
    background-color: {bg_overlay};
    color: {text_primary};
    border-color: {border_muted};
}}
QPushButton:pressed {{
    background-color: {bg_overlay};
}}
QPushButton:disabled {{
    color: {text_muted};
    border-color: {border};
}}
QPushButton[accent="true"] {{
    background-color: {accent};
    color: {bg_base};
    border: none;
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background-color: {accent_hover};
}}

/* ====== 툴바 ====== */
QToolBar {{
    background-color: {bg_surface};
    border-bottom: 1px solid {border};
    spacing: 4px;
    padding: 4px 8px;
}}
QToolBar::separator {{
    background: {border};
    width: 1px;
    margin: 4px 2px;
}}

/* ====== 메뉴 ====== */
QMenu {{
    background-color: {bg_elevated};
    border: 1px solid {border_muted};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
    border-radius: 3px;
    color: {text_primary};
}}
QMenu::item:selected {{
    background-color: {bg_overlay};
}}
QMenu::item:disabled {{
    color: {text_muted};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 3px 0;
}}

/* ====== 트리 (카테고리) ====== */
QTreeWidget {{
    background-color: transparent;
    border: none;
    outline: none;
}}
QTreeWidget::item {{
    padding: 3px 4px;
    border-radius: 3px;
    color: {text_secondary};
}}
QTreeWidget::item:hover {{
    background-color: {bg_overlay};
    color: {text_primary};
}}
QTreeWidget::item:selected {{
    background-color: {bg_overlay};
    color: {text_primary};
    border-left: 2px solid {accent};
}}
QTreeWidget::branch {{
    background: transparent;
}}

/* ====== 테이블 ====== */
QTableWidget {{
    background-color: {bg_base};
    border: none;
    gridline-color: {border};
    outline: none;
}}
QTableWidget::item {{
    padding: 4px 6px;
    color: {text_secondary};
    border-bottom: 1px solid {border};
}}
QTableWidget::item:selected {{
    background-color: {bg_overlay};
    color: {text_primary};
}}
QHeaderView::section {{
    background-color: {bg_surface};
    color: {text_muted};
    border: none;
    border-bottom: 1px solid {border};
    padding: 4px 6px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ====== 탭 ====== */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {border};
}}
QTabBar::tab {{
    background: transparent;
    color: {text_muted};
    padding: 6px 14px;
    border-bottom: 2px solid transparent;
    font-size: 11px;
}}
QTabBar::tab:selected {{
    color: {text_primary};
    border-bottom: 2px solid {accent};
}}
QTabBar::tab:hover {{
    color: {text_secondary};
}}

/* ====== 진행 표시줄 ====== */
QProgressBar {{
    background-color: {bg_overlay};
    border: none;
    border-radius: 2px;
    height: 3px;
    text-align: center;
    font-size: 0px;
}}
QProgressBar::chunk {{
    background-color: {progress_fg};
    border-radius: 2px;
}}

/* ====== 상태 표시줄 ====== */
QStatusBar {{
    background-color: {bg_surface};
    color: {text_muted};
    border-top: 1px solid {border};
    font-size: 11px;
    padding: 0 8px;
}}

/* ====== 스크롤 영역 ====== */
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

/* ====== 스플리터 ====== */
QSplitter::handle {{
    background-color: {border};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

/* ====== 슬라이더 ====== */
QSlider::groove:horizontal {{
    background: {bg_overlay};
    height: 3px;
    border-radius: 1px;
}}
QSlider::handle:horizontal {{
    background: {text_primary};
    width: 10px;
    height: 10px;
    border-radius: 5px;
    margin: -4px 0;
}}
QSlider::sub-page:horizontal {{
    background: {progress_fg};
    border-radius: 1px;
}}

/* ====== 텍스트 편집 ====== */
QTextEdit, QPlainTextEdit {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px;
    selection-background-color: {bg_overlay};
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {border_muted};
}}

/* ====== 체크박스/라디오 ====== */
QCheckBox, QRadioButton {{
    color: {text_secondary};
    spacing: 6px;
}}
QCheckBox:hover, QRadioButton:hover {{
    color: {text_primary};
}}
"""


def build_qss(tokens: ThemeTokens) -> str:
    """ThemeTokens를 완전한 QSS 문자열로 변환한다."""
    fields = dataclasses.asdict(tokens)
    # badge_bg는 rgba() 형식이라 중괄호가 없으므로 안전하게 escape 처리 필요 없음
    return _QSS_TEMPLATE.format(**fields)
