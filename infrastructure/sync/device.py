"""설치 식별자(install_id)와 Lamport 논리시계.

둘 다 ISecretStore(keyring/파일)에 영속한다 — DB 밖이라 스냅샷 교체와 독립이며,
시작 pull이 DB를 열기 전에도 접근 가능하다.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:  # 타입 힌트 전용 — 런타임엔 구조적 타이핑(application import 회피)
    from application.sync.ports import ISecretStore


class Device:
    """이 설치의 고유 식별자를 제공(최초 1회 생성 후 영속)."""

    def __init__(self, secret_store: "ISecretStore", key: str = "device_id") -> None:
        self._store = secret_store
        self._key = key
        self._lock = threading.Lock()
        self._cached: str | None = None

    def install_id(self) -> str:
        with self._lock:
            if self._cached:
                return self._cached
            value = self._store.get(self._key)
            if not value:
                value = str(uuid4())
                self._store.set(self._key, value)
            self._cached = value
            return value


class LamportClock:
    """단조 증가 Lamport 시계. 로컬 이벤트마다 tick(), 원격 관측 시 observe()."""

    def __init__(self, secret_store: "ISecretStore", key: str = "lamport") -> None:
        self._store = secret_store
        self._key = key
        self._lock = threading.Lock()

    def current(self) -> int:
        raw = self._store.get(self._key)
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    def tick(self) -> int:
        """다음 로컬 lamport 값을 반환하고 영속한다."""
        with self._lock:
            nxt = self.current() + 1
            self._store.set(self._key, str(nxt))
            return nxt

    def observe(self, seen: int) -> None:
        """원격에서 관측한 lamport를 반영 — 다음 tick이 이보다 크도록 보장한다."""
        with self._lock:
            if seen > self.current():
                self._store.set(self._key, str(seen))
