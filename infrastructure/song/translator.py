from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")

# Google 번역 백엔드가 과부하/차단일 때 돌려주는 표준 오류 페이지 문구 —
# HTTP 상태코드는 200(정상)인데 응답 본문만 이 오류 페이지라 deep-translator가
# 예외를 던지지 않고 그 텍스트를 "번역 결과"로 그대로 돌려준다(실측 재현됨).
# 이 문구가 섞여 있으면 번역이 아니라 오류 페이지로 보고 원문을 유지한다.
_ERROR_PAGE_MARKERS = ("that's an error", "server error", "that's all we know")


def _is_error_page_text(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _ERROR_PAGE_MARKERS)


class DeepTranslatorAdapter:
    """deep-translator(Google 웹 번역) 기반 번역기 — API 키 불필요.

    ``domain.song.ports.ITranslator``를 구조적으로 만족한다. 라이브러리 미설치나
    네트워크 실패 시 원문을 그대로 반환해(길이 보존) 호출부가 원문/번역을 1:1로
    짝지을 수 있게 한다. QThread에서만 호출한다(네트워크 I/O).
    """

    def __init__(self) -> None:
        self._available: bool | None = None

    def _check(self) -> bool:
        if self._available is None:
            try:
                import deep_translator  # noqa: F401, PLC0415
                self._available = True
            except Exception:
                logger.warning("deep-translator 미설치 — 가사 번역을 건너뜁니다(원문만 표시)")
                self._available = False
        return self._available

    def detect_language(self, text: str) -> str:
        """한글 포함 여부로 한국어를 우선 판별한다(오프라인·빠름).

        한글이 일정 비율 이상이면 'ko', 아니면 ""(미상)을 반환해 번역 여부만 가른다.
        """
        if not text:
            return ""
        hangul = len(_HANGUL_RE.findall(text))
        letters = len(re.findall(r"\w", text))
        if letters and hangul / letters >= 0.3:
            return "ko"
        return ""

    def translate(self, texts: list[str], target: str = "ko", source: str = "auto") -> list[str]:
        if not texts or not self._check():
            return list(texts)
        try:
            from deep_translator import GoogleTranslator  # noqa: PLC0415
        except Exception:
            logger.exception("deep-translator 임포트 실패")
            return list(texts)

        result = list(texts)
        translator = GoogleTranslator(source=source, target=target)
        # 빈 줄은 번역 대상에서 제외(placeholder 유지)
        pending = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        # 줄 단위로 직접 호출한다(``translate_batch``는 내부적으로 이 호출을 그대로
        # for문으로 도는 것뿐이라 한 줄이 예외를 던지면 그 뒤 줄까지 전부 버려진다 —
        # 여기서 줄마다 독립적으로 try/except해 한 줄의 실패가 나머지에 번지지 않게 한다).
        for idx, orig in pending:
            tr = self._translate_one(translator, orig)
            if tr is not None:
                result[idx] = tr
        return result

    def _translate_one(self, translator, text: str) -> str | None:
        """한 줄을 번역한다. 실패하거나 결과가 오류 페이지 본문이면 1회 재시도하고,
        그래도 안 되면 None(호출부가 원문을 유지)을 반환한다.
        """
        for _attempt in range(2):
            try:
                tr = translator.translate(text)
            except Exception:
                logger.exception("가사 번역 실패(줄 단위) — 재시도/원문 유지")
                continue
            if tr and tr.strip() and not _is_error_page_text(tr):
                return tr
            if tr and _is_error_page_text(tr):
                logger.warning("번역 백엔드 오류 페이지 응답 감지 — 재시도/원문 유지")
        return None
