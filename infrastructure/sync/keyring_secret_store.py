"""OS keyring 기반 비밀 저장 (ISecretStore 구현).

동기 자격증명·install_id·lamport는 **DB 밖**에 둔다 — 시작 pull이 DB를 열기 전에
교체하므로 그 시점엔 DB에서 값을 읽을 수 없기 때문이다.

Windows(주 대상)에서는 Windows Credential Manager를 쓴다. keyring 백엔드가 없는
환경(일부 Linux/CI)에서는 DATA_DIR 하위 파일로 graceful 폴백한다(경고 로그).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class KeyringSecretStore:
    """ISecretStore를 구조적으로 만족. keyring 우선, 불가 시 파일 폴백."""

    def __init__(self, service: str, fallback_path: Path, use_file: bool = False) -> None:
        self._service = service
        self._fallback_path = Path(fallback_path)
        self._lock = threading.Lock()
        self._keyring = None if use_file else self._probe_keyring()

    def _probe_keyring(self):
        try:
            import keyring  # noqa: PLC0415
            from keyring.backends.fail import Keyring as _Fail  # noqa: PLC0415

            if isinstance(keyring.get_keyring(), _Fail):
                raise RuntimeError("사용 가능한 keyring 백엔드 없음")
            return keyring
        except Exception as exc:
            # keyring 미설치·백엔드 부재는 **예상된 폴백**이라 트레이스백 없이 한 줄 경고만 남긴다
            # (파일 폴백으로 정상 동작). 상세는 debug에만.
            logger.warning(
                "keyring 사용 불가(%s) — 파일 폴백 사용(%s). 프로덕션(Windows)에서는 keyring 권장.",
                exc, self._fallback_path,
            )
            logger.debug("keyring 프로브 상세", exc_info=True)
            return None

    # -- ISecretStore -----------------------------------------------------
    def get(self, key: str) -> str | None:
        with self._lock:
            if self._keyring is not None:
                try:
                    return self._keyring.get_password(self._service, key)
                except Exception:
                    logger.exception("keyring get 실패: %s", key)
                    return None
            return self._file_read().get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            if self._keyring is not None:
                try:
                    self._keyring.set_password(self._service, key, value)
                    return
                except Exception:
                    logger.exception("keyring set 실패: %s", key)
                    return
            data = self._file_read()
            data[key] = value
            self._file_write(data)

    def delete(self, key: str) -> None:
        with self._lock:
            if self._keyring is not None:
                try:
                    self._keyring.delete_password(self._service, key)
                except Exception:
                    logger.debug("keyring delete 건너뜀(미존재 가능): %s", key)
                return
            data = self._file_read()
            if key in data:
                del data[key]
                self._file_write(data)

    # -- 파일 폴백 --------------------------------------------------------
    def _file_read(self) -> dict[str, str]:
        if not self._fallback_path.exists():
            return {}
        try:
            return json.loads(self._fallback_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.exception("비밀 파일 읽기 실패: %s", self._fallback_path)
            return {}

    def _file_write(self, data: dict[str, str]) -> None:
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._fallback_path.with_suffix(self._fallback_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._fallback_path)
