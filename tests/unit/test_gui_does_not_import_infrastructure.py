"""`gui/`는 `infrastructure/`를 임포트하지 않는다 — 레이어 규칙을 AST로 지킨다.

의존 방향은 `gui → application → domain ← infrastructure`다. 예전에는 화면이 인프라를
22곳에서 직접 불러왔다(쿠키 인증·워치 폴더·Gemini 추출기·중계·자막). 대부분 함수 안의
지연 임포트라 눈에 잘 띄지 않았고, 그래서 **새로 늘어나도 아무도 몰랐다**.

지금은 화면이 쓰는 인프라 기능을 `domain/shared/ports.py`의 포트로 두고, 구체 구현은
조립 루트(`bootstrap/`)가 생성자로 넣는다(`MainWindow`의 `auth_service`·
`watch_folder_scan`·`media`, `gui/media_services.py`).

## 무엇을 세나

`gui/**/*.py`의 **모든** `import infrastructure...`·`from infrastructure... import`.
모듈 최상단뿐 아니라 함수 안(지연 임포트)과 `if TYPE_CHECKING:` 블록도 센다 —
타입 힌트만을 위한 임포트도 허용하지 않는다. 타입이 필요하면 포트(Protocol)를
쓴다. 허용하면 "타입만"이 어느새 런타임 임포트로 번지고, 무엇보다 화면이 인프라의
구체 형에 묶여 있다는 사실이 가려진다.

## 허용 목록

비어 있어야 한다. 정말 옮길 수 없는 것이 생기면 (경로, 모듈) 쌍을 **이유와 함께**
적는다.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GUI = _ROOT / "gui"

# (gui/ 기준 경로, 임포트한 모듈) — 이유
_ALLOWED: set[tuple[str, str]] = set()


def _is_infrastructure(module: str | None) -> bool:
    return bool(module) and (module == "infrastructure" or module.startswith("infrastructure."))


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(_GUI.rglob("*.py")):
        rel = path.relative_to(_GUI).as_posix()
        if "__pycache__" in rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            for module in modules:
                if _is_infrastructure(module) and (rel, module) not in _ALLOWED:
                    found.append(f"gui/{rel}:{node.lineno}: {module}")
    return found


def test_gui_does_not_import_infrastructure():
    found = _violations()
    assert not found, (
        "gui/가 infrastructure/를 임포트한다 — 포트(domain/shared/ports.py)로 받고 "
        "구체 구현은 bootstrap/에서 주입할 것:\n" + "\n".join(found)
    )


def test_allowlist_is_empty():
    """예외를 두면 이유가 있어야 한다 — 지금은 하나도 없다."""
    assert _ALLOWED == set()


def test_detects_every_form(tmp_path, monkeypatch):
    """검사기가 지연 임포트·TYPE_CHECKING·`import x.y`를 모두 잡는지."""
    gui = tmp_path / "gui"
    gui.mkdir()
    (gui / "sample.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from infrastructure.auth.youtube_auth import YouTubeAuthService\n"
        "import infrastructure.streaming\n"
        "def f():\n"
        "    from infrastructure import streaming  # noqa\n"
        "from infrastructure_like import x\n"
        "from .infrastructure import y\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "_GUI", gui)
    found = _violations()
    assert sorted(int(ln.split(":")[1]) for ln in found) == [3, 4, 6]
