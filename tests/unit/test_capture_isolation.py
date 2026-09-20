"""설명서 갈무리가 사용자의 실제 자료를 읽지 않는지 — 실제로 샜던 경로를 고정한다.

v1.32.0 갈무리에 **사용자의 즐겨찾기 항목이 찍혀 공개 저장소와 설치본에 들어갔다.**
DB만 임시본으로 바꿨는데, 설정(`data/config.yaml`)과 즐겨찾기(OS 사용자 데이터 경로)는
따라오지 않았기 때문이다. 이제 `OVC_DATA_DIR` 하나로 셋을 함께 옮긴다.

이 시험이 지키는 것은 두 가지다.
1. 그 환경 변수를 **읽어야 할 곳이 전부 읽는가**.
2. 갈무리 스크립트가 그 변수를 **앱 모듈을 불러오기 전에** 세우는가 — 경로 상수는
   모듈을 불러올 때 정해지므로, 위쪽에 임포트를 한 줄 더하면 격리가 조용히 깨진다.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "capture_screenshots.py"

# 갈무리 스크립트가 격리를 세우기 전에 불러서는 안 되는 패키지들.
_APP_PACKAGES = {
    "config", "bootstrap", "gui", "application", "domain", "infrastructure", "utils",
}


def _run_isolated(code: str, data_dir: Path) -> str:
    """별도 프로세스에서 `OVC_DATA_DIR` 을 세우고 코드를 돌린다.

    같은 프로세스에서는 `config.settings` 가 이미 불려 있어 경로 상수가 굳어 있다 —
    실제 동작을 보려면 프로세스를 새로 띄워야 한다.
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=_ROOT,
        env={"PATH": "", "SystemRoot": "C:\\Windows", "OVC_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip()


class TestEnvOverrideIsHonored:
    def test_설정_경로가_따라간다(self, tmp_path):
        out = _run_isolated(
            """
            import sys; sys.path.insert(0, '.')
            import config.settings as s
            print(s.DATA_DIR)
            print(s.DATABASE_PATH)
            """,
            tmp_path,
        ).splitlines()
        assert Path(out[0]) == tmp_path
        assert Path(out[1]) == tmp_path / "library.db"

    def test_즐겨찾기_파일도_따라간다(self, tmp_path):
        """여기만 OS 사용자 데이터 경로를 쓴다 — 빠뜨리기 쉬운 곳이고, 실제로 샜다."""
        out = _run_isolated(
            """
            import sys; sys.path.insert(0, '.')
            from application.library import favorites
            print(favorites._STORE_PATH)
            """,
            tmp_path,
        )
        assert Path(out) == tmp_path / "favorites.json"

    def test_변수가_없으면_기본_경로_그대로(self):
        """평소 동작은 건드리지 않는다 — 사용자 데이터가 다른 곳으로 옮겨지면 큰일이다."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'.'); import config.settings as s; print(s.DATA_DIR)"],
            cwd=_ROOT, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert Path(result.stdout.strip()) == _ROOT / "data"


class TestCaptureScriptSetsEnvFirst:
    """스크립트 위쪽에 앱 임포트가 끼어들면 격리가 조용히 깨진다."""

    def _tree(self):
        return ast.parse(_SCRIPT.read_text(encoding="utf-8"))

    def _env_assign_line(self, tree) -> int:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Attribute)
                and node.targets[0].value.attr == "environ"
            ):
                return node.lineno
        raise AssertionError("OVC_DATA_DIR 을 세우는 곳을 찾지 못했다")

    def test_앱_모듈보다_먼저_세운다(self):
        tree = self._tree()
        env_line = self._env_assign_line(tree)
        early = []
        for node in tree.body:      # 모듈 최상위만 본다(함수 안 임포트는 늦게 실행된다)
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if node.lineno >= env_line:
                continue
            names = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            early += [n for n in names if n.split(".")[0] in _APP_PACKAGES]
        assert not early, f"격리 전에 앱 모듈을 불러온다: {early}"

    def test_샌드박스는_사용자_홈_밖이다(self):
        """윈도우 임시 폴더는 사용자 홈 아래라 설정 화면 갈무리에 이름이 찍힌다."""
        src = _SCRIPT.read_text(encoding="utf-8")
        assert "mkdtemp" not in src, "시스템 임시 폴더를 쓰면 경로에 사용자 이름이 들어간다"
        assert '_ROOT / "build"' in src
