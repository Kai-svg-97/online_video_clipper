"""keyring 서비스 이름은 데이터 폴더 단위다 — OS 전역 저장소가 격리를 깨지 않게.

keyring(Windows 자격 증명 관리자)은 OS 사용자 하나에 하나다. 이름을 고정해 두었더니
keyring이 있는 환경(CI 러너, 실제 사용자 PC)에서만 동기화 시험의 "두 기기"가 install_id를
공유해 실패했다. keyring이 없는 개발 파이썬은 파일 폴백이 폴더별로 갈라 주어 가려졌다.

그래서 이 시험은 keyring 설치 여부와 무관하게 **이름**만 본다 — 환경 탓에 가려지지 않게.
"""

from __future__ import annotations

from pathlib import Path

from infrastructure.persistence.database import Database
from infrastructure.sync.keyring_secret_store import scoped_service
from infrastructure.sync.sync_service import _KEYRING_SERVICE, SyncService


class TestScopedService:
    def test_기본_폴더는_이름을_바꾸지_않는다(self, tmp_path):
        """바꾸면 기존 사용자가 저장해 둔 토큰을 찾지 못해 로그아웃된 것처럼 보인다."""
        assert scoped_service("svc", tmp_path, tmp_path) == "svc"

    def test_다른_폴더는_다른_이름이다(self, tmp_path):
        default = tmp_path / "data"
        a = scoped_service("svc", tmp_path / "a", default)
        b = scoped_service("svc", tmp_path / "b", default)
        assert a != "svc" and b != "svc"
        assert a != b
        assert a.startswith("svc@")

    def test_같은_폴더는_늘_같은_이름이다(self, tmp_path):
        """다시 시작해도 같은 비밀값을 찾아야 한다 — 경로 표기(대소문자·상대 경로)와 무관하게."""
        default = tmp_path / "data"
        first = scoped_service("svc", tmp_path / "Sandbox", default)
        again = scoped_service("svc", Path(str(tmp_path / "sandbox")), default)
        assert first == again


class TestSyncServiceUsesScopedStore:
    def test_두_데이터_폴더는_비밀_저장소_이름이_다르다(self, tmp_path):
        """keyring이 있으면 이 이름이 곧 저장 위치다 — 같으면 install_id를 공유한다."""
        names = []
        for name in ("A", "B"):
            db = Database(tmp_path / f"{name}.db")
            db.initialize()
            svc = SyncService(db, data_dir=tmp_path / name)
            names.append(svc._secret._service)
        assert names[0] != names[1]
        assert all(n.startswith(f"{_KEYRING_SERVICE}@") for n in names)
