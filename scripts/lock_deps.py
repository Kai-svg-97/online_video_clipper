"""`constraints.txt` 를 다시 만든다 — CI·릴리즈 빌드가 쓰는 의존성 버전 고정.

`requirements*.txt` 는 **무엇이 필요한가**(`>=` 하한)만 적는다. 그것만으로 설치하면
설치하는 날의 최신판이 들어와서, 같은 태그를 다시 빌드해도 결과가 달라지고 로컬과 CI의
린트·테스트가 어긋난다(실제로 로컬 ruff 0.15 ↔ CI가 받을 ruff 0.16). 그래서 **몇 버전으로
빌드하는가**를 여기서 따로 고정하고, 워크플로는 `pip install -r ... -c constraints.txt` 로
설치한다.

**yt-dlp 는 고정하지 않는다.** YouTube가 바뀌면 옛 yt-dlp는 다운로드가 깨진다 — 릴리즈에는
늘 그날의 최신판이 들어가야 한다. 고정하면 앱의 핵심 기능이 조용히 낡는다.

설치하지 않고 풀기만 한다(`pip install --dry-run --report`). 빌드 대상(Python 3.12,
Windows x64)의 휠로 푼다 — 개발 PC의 파이썬 버전이 달라도 결과는 같다.

사용:
    python scripts/lock_deps.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "constraints.txt"

# release.yml / test.yml 의 setup-python 과 같아야 한다.
PYTHON_VERSION = "3.12"
PLATFORM = "win_amd64"

# 고정하지 않는 패키지 — 이유는 모듈 설명 참조.
# yt-dlp-ejs 는 yt-dlp 가 정확한 버전을 요구하며 그 버전은 yt-dlp 와 함께 바뀐다 —
# 고정하면 최신 yt-dlp 설치와 충돌한다.
UNPINNED = {"yt-dlp", "yt-dlp-ejs"}

_HEADER = """\
# 자동 생성 — 손으로 고치지 말고 `python scripts/lock_deps.py` 로 다시 만든다.
# 빌드 대상: Python {py} / {platform}. 설치: pip install -r requirements-dev.txt -c constraints.txt
# 고정하지 않음: {unpinned} (YouTube 변화를 따라가야 한다 — scripts/lock_deps.py 설명)
"""


def resolve() -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "-r", str(_ROOT / "requirements-dev.txt"),
                "--dry-run", "--ignore-installed", "--quiet",
                "--python-version", PYTHON_VERSION,
                "--platform", PLATFORM,
                "--only-binary=:all:",
                "--report", str(report),
            ],
            check=True,
            cwd=_ROOT,
        )
        data = json.loads(report.read_text(encoding="utf-8"))
    return {
        item["metadata"]["name"].lower(): item["metadata"]["version"]
        for item in data["install"]
    }


def render(pins: dict[str, str]) -> str:
    lines = [
        _HEADER.format(py=PYTHON_VERSION, platform=PLATFORM, unpinned=", ".join(sorted(UNPINNED)))
    ]
    lines += [f"{name}=={ver}" for name, ver in sorted(pins.items()) if name not in UNPINNED]
    return "\n".join(lines) + "\n"


def main() -> int:
    pins = resolve()
    OUT.write_text(render(pins), encoding="utf-8", newline="\n")
    kept = sum(1 for n in pins if n not in UNPINNED)
    print(f"만들었습니다: {OUT.relative_to(_ROOT)}  ({kept}개 고정, 제외: {', '.join(sorted(UNPINNED))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
