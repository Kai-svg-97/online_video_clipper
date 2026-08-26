"""전체 앱 QSS 빌더.

build_qss(tokens) 로 ThemeTokens를 완전한 Qt StyleSheet 문자열로 변환한다.
QApplication.instance().setStyleSheet(qss) 에 직접 적용된다.

디자인 방향 — **조밀한 프로 툴**(Linear·Arc 계열):
- 반지름은 컨트롤 6px, 작은 항목 4px로 통일한다(예전엔 3·4·6px가 섞여 있었다).
- **툴바 한 줄의 컨트롤 높이를 명시한다.** 보기 전환 버튼은 코드에서
  `setFixedSize(28, 28)`로 고정돼 있는데, 옆의 검색창·정렬 콤보 높이는 폰트 메트릭에서
  emergent하게 나온다. Windows 기본 폰트에서는 우연히 28px로 맞지만 폰트·플랫폼이
  바뀌면 어긋난다(실측: `offscreen` 플랫폼에서는 26px로 2px 내려갔다). 그래서
  `min-height`로 행 높이를 못박아 환경에 무관하게 같은 줄로 맞춘다.
- 툴바성 버튼은 평소 배경이 없고(ghost) 호버에서만 반응한다. 대화상자의 실행
  버튼처럼 눌러야 하는 것은 배경을 유지해 위계를 만든다.
- **호버는 배경 틴트만으로는 부족하다.** 11개 프리셋에서 `bg_overlay`와 배경의
  대비가 1.08~1.32:1뿐이라(실측) 틴트만 걸면 반응이 없어 보인다. 그래서 호버는
  항상 틴트 + **글자색 승급**(`text_secondary` → `text_primary`, 전 테마 5.8:1 이상)을
  함께 건다.
- 포커스는 accent 링으로 표시한다. 예전에는 `border_muted`로만 바꿔서 기본
  테두리와 구분되지 않았다(전 테마 accent는 입력 배경 대비 5.22:1 이상).

색은 전부 ThemeTokens에서 파생한다. 파생값(accent 틴트)은 `build_qss`가 만든다.
"""
from __future__ import annotations

import dataclasses

from gui.themes.tokens import ThemeTokens


def _rgba(hex_color: str, alpha: float) -> str:
    """토큰 색을 알파를 입힌 rgba() 문자열로 바꾼다(QSS 틴트용)."""
    raw = hex_color.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


# ---------------------------------------------------------------------------
# QSS 템플릿 — {token_name} 자리표시자는 ThemeTokens 필드명 + build_qss의 파생값
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

/* ====== 툴팁 ======
   QSS가 없으면 OS 기본(흰 배경·검은 글자)이 나와 어두운 테마와 정면으로 충돌한다. */
QToolTip {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border_muted};
    border-radius: 6px;
    padding: 4px 8px;
}}

/* ====== 스크롤바 ======
   손잡이는 '잡아야 하는' 컨트롤이라 트랙과 구분돼야 한다. 예전엔 손잡이가
   bg_overlay라 11개 테마 전부에서 트랙 대비 1.08~1.32:1로 사실상 보이지 않았다.
   text_muted로 올려 4.55~6.23:1을 확보한다(test_scrollbar_handle_is_findable). */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {text_muted};
    border-radius: 3px;
    min-height: 32px;
    margin: 2px 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: {text_secondary};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {text_muted};
    border-radius: 3px;
    min-width: 32px;
    margin: 3px 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {text_secondary};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ====== 입력 필드 ====== */
QLineEdit {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 18px;   /* +패딩8 +테두리2 = 28px — 보기전환 버튼과 같은 행 높이 */
    selection-background-color: {accent};
    selection-color: {text_on_accent};
}}
QLineEdit:hover {{
    border-color: {border_muted};
}}
QLineEdit:focus {{
    border: 1px solid {accent};
}}
QLineEdit:disabled {{
    color: {text_muted};
    background-color: {bg_surface};
    border-color: {border};
}}
/* placeholder 글자색은 QSS로 지정할 수 없다 — Qt에는 그 속성이 없고
   `QPalette.ColorRole.PlaceholderText`가 담당한다(기본은 본문색의 반투명).
   여기에 `::placeholder` 규칙을 쓰면 조용히 무시되는 죽은 CSS가 된다. */

/* 숫자·시간 입력도 같은 어법을 따른다(예전엔 규칙이 없어 기본 위젯 룩이었다). */
QSpinBox, QDoubleSpinBox, QTimeEdit {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 3px 6px;
    selection-background-color: {accent};
    selection-color: {text_on_accent};
}}
QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {{
    border: 1px solid {accent};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled, QTimeEdit:disabled {{
    color: {text_muted};
    background-color: {bg_surface};
}}

/* ====== 콤보 박스 ======
   예전엔 규칙이 전혀 없어 정렬 드롭다운만 OS 기본 룩으로 튀었다. */
QComboBox {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 18px;   /* 툴바 정렬 — QLineEdit과 동일 */
}}
QComboBox:hover {{
    border-color: {border_muted};
}}
QComboBox:focus {{
    border: 1px solid {accent};
}}
QComboBox:disabled {{
    color: {text_muted};
    background-color: {bg_surface};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {text_muted};
    width: 0;
    height: 0;
    margin-right: 6px;
}}
QComboBox::down-arrow:hover {{
    border-top-color: {text_primary};
}}
QComboBox QAbstractItemView {{
    background-color: {bg_elevated};
    border: 1px solid {border_muted};
    border-radius: 6px;
    padding: 3px;
    selection-background-color: {accent_tint_active};
    selection-color: {text_primary};
    outline: none;
}}

/* ====== 버튼 ======
   두 위계: 기본 버튼은 배경을 유지하고, flat 버튼(툴바성)은 ghost로 둔다.
   호버는 틴트 + 글자색 승급을 함께 건다(틴트만으로는 대비가 1.1~1.3:1뿐이다). */
QPushButton {{
    background-color: {bg_elevated};
    color: {text_secondary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 12px;
}}
QPushButton:hover {{
    background-color: {bg_overlay};
    color: {text_primary};
    border-color: {border_muted};
}}
QPushButton:pressed {{
    background-color: {accent_tint_active};
    color: {text_primary};
}}
QPushButton:focus {{
    border: 1px solid {accent};
}}
QPushButton:disabled {{
    color: {text_muted};
    background-color: {bg_surface};
    border-color: {border};
}}
QPushButton:checked {{
    background-color: {accent_tint_active};
    color: {accent};
    border-color: {accent};
}}

/* flat 버튼 = ghost. 저장소 전반에서 이미 setFlat(True)로 툴바성 버튼을 표시한다. */
QPushButton[flat="true"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {text_secondary};
}}
QPushButton[flat="true"]:hover {{
    background-color: {bg_overlay};
    color: {text_primary};
}}
QPushButton[flat="true"]:pressed {{
    background-color: {accent_tint_active};
}}

/* 강조 버튼 — accent 배경 위 글자는 반드시 text_on_accent를 쓴다.
   예전에는 bg_base를 썼는데, 그 조합은 대비 보장이 없어(테스트도 없었다)
   밝은 테마에서 묻힐 수 있었다. text_on_accent는 전 테마 4.5:1 이상이 검증된다. */
QPushButton[accent="true"] {{
    background-color: {accent};
    color: {text_on_accent};
    border: 1px solid {accent};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background-color: {accent_hover};
    border-color: {accent_hover};
    color: {text_on_accent};
}}
QPushButton[accent="true"]:disabled {{
    background-color: {bg_overlay};
    color: {text_muted};
    border-color: {border};
}}

/* ====== 툴 버튼 ======
   라이브러리 툴바(보기 유형)·사이드바·앨범 화면이 쓴다. 예전엔 규칙이 전혀 없어
   기본 위젯 룩이었다. ghost + 호버 틴트, 선택은 accent 틴트로 확실히 구분한다
   (호버와 선택이 같은 색이면 지금 무엇이 켜져 있는지 알 수 없다).
   플레이어 컨트롤바는 자기 위젯 스타일시트를 갖고 있어 여기 규칙보다 우선한다. */
QToolButton {{
    background-color: transparent;
    color: {text_secondary};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px 6px;
}}
QToolButton:hover {{
    background-color: {bg_overlay};
    color: {text_primary};
}}
QToolButton:pressed {{
    background-color: {accent_tint_active};
}}
QToolButton:checked {{
    background-color: {accent_tint_active};
    color: {accent};
    border-color: {accent};
}}
QToolButton:disabled {{
    color: {text_muted};
    background-color: transparent;
}}
QToolButton::menu-indicator {{
    image: none;
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
    border-radius: 4px;
    color: {text_primary};
}}
QMenu::item:selected {{
    background-color: {accent_tint_active};
}}
QMenu::item:disabled {{
    color: {text_muted};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 3px 0;
}}

/* ====== 트리 (카테고리) ======
   행 배경·선택 표시·셰브론은 _TreeRowDelegate와 _PlaylistTree.drawBranches()가
   직접 그린다. 따라서 여기에 ::item / ::branch 배경 규칙을 두면 델리게이트가 그린
   위에 겹치거나(또는 우회되어) 죽은 CSS가 된다 — 컨테이너 속성만 남긴다. */
QTreeWidget, QTreeView {{
    background-color: transparent;
    border: none;
    outline: none;
}}
QTreeWidget::branch {{
    background: transparent;
    image: none;
}}

/* ====== 리스트 ======
   즐겨찾기 바·태그 목록·영상 그리드가 쓴다. 항목을 델리게이트가 그리는 목록은
   자기 스타일시트로 배경을 투명하게 덮으므로 여기 규칙과 충돌하지 않는다. */
QListWidget, QListView {{
    background-color: transparent;
    border: none;
    outline: none;
}}
QListWidget::item, QListView::item {{
    border-radius: 4px;
    padding: 2px;
}}
QListWidget::item:selected, QListView::item:selected {{
    background-color: {accent_tint_active};
    color: {text_primary};
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
    background-color: {accent_tint_active};
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

/* ====== 그룹 박스 ====== */
QGroupBox {{
    border: 1px solid {border};
    border-radius: 6px;
    margin-top: 10px;
    padding: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {text_muted};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
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
QTabBar::tab:hover:!selected {{
    color: {text_secondary};
    background-color: {bg_overlay};
}}

/* ====== 진행 표시줄 ====== */
QProgressBar {{
    background-color: {bg_overlay};
    border: none;
    border-radius: 2px;
    height: 3px;
    text-align: center;
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
QSplitter::handle:hover {{
    background-color: {accent};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

/* ====== 슬라이더 ======
   영상 위에 겹치는 플레이어 슬라이더는 QSS가 먹지 않아 _TrackSlider가 직접 그린다.
   여기 규칙은 그 밖(설정·다이얼로그)의 일반 슬라이더용이다. */
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

/* ====== 텍스트 편집 ======
   QTextBrowser는 QTextEdit의 서브클래스라 이 규칙이 함께 적용된다. */
QTextEdit, QPlainTextEdit {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
    selection-background-color: {accent};
    selection-color: {text_on_accent};
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {accent};
}}

/* ====== 체크박스/라디오 ====== */
QCheckBox, QRadioButton {{
    color: {text_secondary};
    spacing: 6px;
}}
QCheckBox:hover, QRadioButton:hover {{
    color: {text_primary};
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {text_muted};
}}
"""


def build_qss(tokens: ThemeTokens) -> str:
    """ThemeTokens를 완전한 QSS 문자열로 변환한다.

    토큰 필드에 더해 파생값(accent 틴트)을 자리표시자로 제공한다. 틴트를 토큰으로
    두지 않는 이유는 값이 accent에서 기계적으로 나오기 때문이다 — 프리셋마다 손으로
    적으면 accent를 바꿀 때 같이 고치는 것을 잊는다.
    """
    fields = dataclasses.asdict(tokens)
    # 호버보다 한 단계 강한 상태(눌림·선택·메뉴 강조)에 쓰는 accent 틴트.
    # 0.18에서 본문 글자 대비가 전 테마 9.57:1 이상으로 확인됐다(실측).
    fields["accent_tint_active"] = _rgba(tokens.accent, 0.18)
    fields["accent_tint_hover"] = _rgba(tokens.accent, 0.10)
    return _QSS_TEMPLATE.format(**fields)
