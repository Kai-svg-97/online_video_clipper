"""애플리케이션 전역 로깅 설정.

이전에는 예외를 `except Exception: pass`로 조용히 삼켜 장애 진단이 불가능했다.
이 모듈은 회전 파일 핸들러(LOG_DIR/app.log)와 콘솔 핸들러를 설정해,
삼켜진 예외도 `logger.exception(...)`으로 기록되어 사후 진단이 가능하게 한다.

사용법:
    # 진입점(main.py)에서 1회 호출
    from utils.logging_config import setup_logging
    setup_logging()

    # 각 모듈 상단에서
    import logging
    logger = logging.getLogger(__name__)
    ...
    except Exception:
        logger.exception("메타데이터 조회 실패")  # 동작은 그대로 두되 흔적을 남긴다
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config.settings import LOG_DIR

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_BACKUP_COUNT = 3

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """루트 로거에 파일 + 콘솔 핸들러를 설정한다 (중복 호출 안전).

    저사양 PC 대상이므로 파일 크기를 2MB×3개로 제한한다.
    """
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "app.log"

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _configured = True
    logging.getLogger(__name__).info("로깅 초기화 완료 — 로그 파일: %s", log_file)
