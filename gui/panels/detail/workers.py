"""상세화면이 띄우는 백그라운드 워커(Gemini 요약 추출).

실행 중 파괴되면 앱이 죽으므로 반드시 `gui/workers.py`의 track/retire를 거친다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QThread,
    pyqtSignal,
)



logger = logging.getLogger(__name__)


class _GeminiSummaryWorker(QThread):
    """백그라운드에서 Gemini AI 요약을 추출한다."""

    # (video_id, 언어, 요약 텍스트, 실패 사유) — 성공 시 사유는 빈 문자열.
    # 언어를 돌려주는 이유: 결과가 도착했을 때 어느 언어 칸에 넣을지 받는 쪽이 짐작하지
    # 않게 한다(요약은 언어별로 저장된다).
    done = pyqtSignal(object, str, str, str)

    def __init__(self, url: str, video_id, lang: str = "ko", parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._video_id = video_id
        self._lang = lang

    def run(self) -> None:
        try:
            from infrastructure.browser.gemini_extractor import GeminiExtractor  # noqa: PLC0415
            summary, reason = GeminiExtractor().extract_with_reason(self._url, self._lang)
            self.done.emit(self._video_id, self._lang, summary or "", reason)
        except Exception:
            logger.exception("Gemini 요약 워커 실패")
            self.done.emit(self._video_id, self._lang, "", "error")
