"""faster-whisper 기반 음성 인식 어댑터.

**모델은 앱이 관리하는 폴더에 둔다**(`DATA_DIR/models/whisper`). 기본값인 사용자
HuggingFace 캐시를 쓰면 앱이 받은 것을 앱이 못 지운다 — 지우려는 사용자가 어디를
봐야 할지 알 수 없다.

**무거운 import 는 함수 안에서 한다.** `faster_whisper` 를 끌어오면 ctranslate2·
onnxruntime·numpy 까지 올라와 수백 ms가 든다. 전사를 한 번도 쓰지 않는 사용자가
그 값을 시작할 때마다 치르게 둘 수 없다(CLAUDE.md 의 시작 성능 규칙과 같은 이유).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from config.settings import DATA_DIR
from domain.library.transcribe import MODEL_DIR_NAME, resolve_model, segments_to_cues

logger = logging.getLogger(__name__)

# 저사양 PC가 목표라 CPU·int8 로 고정한다. GPU(cuda)는 사용자의 드라이버 상태에
# 따라 조용히 실패하는 경로가 많아, 되면 좋은 것보다 **항상 되는 것**을 택했다.
_DEVICE = "cpu"
_COMPUTE_TYPE = "int8"


def model_root() -> Path:
    return DATA_DIR / "models" / MODEL_DIR_NAME


class WhisperTranscriber:
    """`ITranscriber` 구현. 모든 메서드를 배경 QThread 에서만 호출한다."""

    def __init__(self) -> None:
        # 모델 하나를 메모리에 올리는 데 수백 MB가 든다 — 같은 모델을 연달아 쓰는
        # 일이 흔하므로(여러 영상 전사) 하나만 붙들고 재사용한다.
        self._loaded_key: str = ""
        self._model = None

    # ── 모델 관리 ──────────────────────────────────────────────────

    def is_model_ready(self, model_key: str) -> bool:
        """이미 받아 둔 모델인가 — 네트워크를 쓰지 않고 판정한다."""
        model = resolve_model(model_key)
        try:
            self._load(model.key, local_files_only=True)
        except Exception:
            return False
        return True

    def download_model(self, model_key: str) -> bool:
        """모델을 받아 둔다. 이미 있으면 곧바로 True.

        진행률은 주지 않는다 — faster-whisper 가 내려받기를 대신 하며 콜백을
        노출하지 않는다. 호출부는 '받는 중'만 알리고 크기를 미리 보여준다.
        """
        model = resolve_model(model_key)
        try:
            self._load(model.key, local_files_only=False)
        except Exception:
            logger.exception("전사 모델 내려받기 실패: %s", model.key)
            return False
        return True

    def installed_models(self) -> set[str]:
        """받아 둔 모델 키 — 설정 화면이 무엇을 지울 수 있는지 보여준다."""
        return {m for m in ("tiny", "base", "small") if self.is_model_ready(m)}

    def delete_model(self, model_key: str) -> bool:
        """받아 둔 모델을 지운다(디스크를 되찾는다)."""
        import shutil  # noqa: PLC0415

        model = resolve_model(model_key)
        # HuggingFace 캐시 규약: `models--<org>--<repo>` 폴더 하나가 모델 하나다.
        target = model_root() / f"models--Systran--faster-whisper-{model.key}"
        if self._loaded_key == model.key:
            self._model = None
            self._loaded_key = ""
        if not target.exists():
            return False
        try:
            shutil.rmtree(target)
        except OSError:
            logger.exception("전사 모델 삭제 실패: %s", target)
            return False
        return True

    # ── 전사 ──────────────────────────────────────────────────────

    def transcribe(
        self,
        media_path: str,
        model_key: str,
        language: str | None = None,
        on_progress: Callable[[float], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[tuple[int, int, str]]:
        """미디어 파일 → 자막 큐 `(시작ms, 끝ms, 텍스트)`.

        `on_progress` 는 0.0~1.0 을 받는다. 전사는 **세그먼트를 하나씩 흘려 주는**
        방식이라 총 길이를 알면 진행률을 만들 수 있다(모르면 호출되지 않는다).

        `should_stop` 이 True 를 돌려주면 **그때까지 나온 것을 돌려준다** — 30분짜리
        영상을 25분까지 전사한 뒤 취소했는데 전부 버리면 그 시간이 날아간다.
        """
        path = Path(media_path)
        if not path.exists():
            raise FileNotFoundError(f"전사할 파일이 없습니다: {path}")

        model = self._load(resolve_model(model_key).key, local_files_only=False)
        segments, info = model.transcribe(str(path), language=language or None)

        total = float(getattr(info, "duration", 0) or 0)
        collected = []
        for seg in segments:
            if should_stop is not None and should_stop():
                logger.info("전사 중단: %s (%d개까지)", path.name, len(collected))
                break
            collected.append(seg)
            if on_progress is not None and total > 0:
                on_progress(min(1.0, float(getattr(seg, "end", 0.0)) / total))
        return segments_to_cues(collected)

    def detect_language(self, media_path: str, model_key: str) -> str:
        """감지된 언어 코드(실패하면 빈 문자열) — 색인 라벨에 쓴다."""
        try:
            model = self._load(resolve_model(model_key).key, local_files_only=False)
            _segments, info = model.transcribe(str(media_path))
            return str(getattr(info, "language", "") or "")
        except Exception:
            logger.exception("언어 감지 실패: %s", media_path)
            return ""

    # ── 내부 ───────────────────────────────────────────────────────

    def _load(self, model_key: str, *, local_files_only: bool):
        if self._model is not None and self._loaded_key == model_key:
            return self._model
        # Windows 에서 심볼릭 링크를 못 만든다는 경고가 매번 뜬다 — 동작에는
        # 문제가 없고(파일을 복사한다) 사용자 로그만 시끄러워져 끈다.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from faster_whisper import WhisperModel  # noqa: PLC0415

        root = model_root()
        root.mkdir(parents=True, exist_ok=True)
        model = WhisperModel(
            model_key,
            device=_DEVICE,
            compute_type=_COMPUTE_TYPE,
            download_root=str(root),
            local_files_only=local_files_only,
        )
        self._model = model
        self._loaded_key = model_key
        return model
