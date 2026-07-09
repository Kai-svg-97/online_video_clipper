from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")
_MAX_BATCH = 40   # deep-translator 대량 요청 시 차단 위험 완화용 청크 크기


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
        for start in range(0, len(pending), _MAX_BATCH):
            chunk = pending[start : start + _MAX_BATCH]
            originals = [t for _, t in chunk]
            try:
                translated = translator.translate_batch(originals)
            except Exception:
                logger.exception("가사 번역 배치 실패 — 해당 청크는 원문 유지")
                continue
            if not isinstance(translated, list) or len(translated) != len(chunk):
                continue
            for (idx, orig), tr in zip(chunk, translated):
                result[idx] = tr if (tr and tr.strip()) else orig
        return result
