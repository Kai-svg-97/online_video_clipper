"""영상 원본 info 캐시 — 같은 영상을 yt-dlp에 여러 번 묻지 않는다(배치 6, B1-1~B1-3).

상세 화면의 load와 ▶, 화질 전환, ⬇ 화질 목록이 모두 같은 URL을 yt-dlp에 따로 물었다
(추출 한 번이 3~4초). 이 캐시는 **처리 전 원본**(`extract_info(process=False)`)을 들고,
화질은 호출 쪽이 `process_ie_result(deepcopy(raw))`로 고른다(네트워크 0건, 약 0.1초).

설계 규칙:
- 키는 `(url, client)`다. 대체 클라이언트는 다른 URL 묶음을 준다.
- **진행 중인 요청을 합친다** — 같은 키를 동시에 물으면 한 번만 추출하고 결과(또는
  예외)를 나눠 받는다. 실패는 캐시하지 않는다.
- TTL은 `min(googlevideo expire - 여유, 상한)`이고, 적중해도 늘리지 않는다. 남은 시간이
  여유 이하면 캐시하지 않는다.
- 항목 수에 상한을 둔다(원본 JSON이 영상당 수백 KB — 메모리 규칙). 오래 안 쓴 것부터 버린다.
- **`fresh=True`는 캐시를 우회**한다 — 중계 refresh·대체 클라이언트·재생 오류 재시도처럼
  낡은 URL이 문제인 경로가 쓴다. 진행 중 요청에도 합류하지 않고, 새 결과로 캐시를 갈아 끼운다.
- 반환 dict는 **공유 객체**다. 호출 쪽은 고치지 않는다(처리 전에 `deepcopy`).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from utils.ytdlp_runtime import js_runtime_opts

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 6
DEFAULT_MAX_TTL_SEC = 1800.0
DEFAULT_MARGIN_SEC = 300.0

_EXPIRE_QUERY = re.compile(r"[?&]expire=([^&/#]*)")
_EXPIRE_PATH = re.compile(r"/expire/([^/?#]*)")


def extract_raw_info(url: str, client: str | None = None) -> dict:
    """원본 info를 받는다(처리 전, 내려받지 않는다). 워커 스레드에서 부른다."""
    from yt_dlp import YoutubeDL  # noqa: PLC0415 (무거운 임포트는 호출 시점에)

    opts = {
        **js_runtime_opts(),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        # 자막 목록을 같은 원본에서 뽑는다 — 이 옵션이 없으면 확장기가 트랙을 채우지 않는다.
        "writesubtitles": True,
        "writeautomaticsub": True,
    }
    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False, process=False) or {}


def _expire_epoch(info: dict) -> float | None:
    """googlevideo URL의 `expire`(epoch 초) 중 가장 이른 값. 못 읽으면 None."""
    found: list[float] = []
    for fmt in info.get("formats") or []:
        url = fmt.get("url") if isinstance(fmt, dict) else None
        if not isinstance(url, str) or "googlevideo" not in url:
            continue
        m = _EXPIRE_QUERY.search(url) or _EXPIRE_PATH.search(url)
        if not m:
            continue
        try:
            found.append(float(int(m.group(1))))
        except ValueError:
            continue
    return min(found) if found else None


class _Inflight:
    __slots__ = ("event", "result", "error", "waiters")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: dict | None = None
        self.error: BaseException | None = None
        self.waiters = 0


class VideoInfoCache:
    """`IVideoInfoSource` 구현 — 스레드 안전."""

    def __init__(
        self,
        extract: Callable[..., dict] = extract_raw_info,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_ttl_sec: float = DEFAULT_MAX_TTL_SEC,
        margin_sec: float = DEFAULT_MARGIN_SEC,
        now: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._extract = extract
        self._max_entries = max(1, max_entries)
        self._max_ttl = max_ttl_sec
        self._margin = margin_sec
        self._now = now
        self._wall = wall
        self._lock = threading.Lock()
        # key → (info, deadline, seq)
        self._entries: OrderedDict[tuple[str, str | None], tuple[dict, float, int]] = OrderedDict()
        self._inflight: dict[tuple[str, str | None], _Inflight] = {}
        self._seq = 0

    def __bool__(self) -> bool:
        return True   # `__len__`이 0이어도 '없음'으로 취급되면 안 된다(`if cache:` 판정)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # ── 공개 ──────────────────────────────────────────────────────
    def info(self, url: str, client: str | None = None, fresh: bool = False) -> dict:
        """원본 info. `fresh`면 캐시·진행 중 요청을 건너뛰고 새로 받아 캐시를 갈아 끼운다."""
        key = (url, client)
        if fresh:
            with self._lock:
                self._seq += 1
                seq = self._seq
            result = self._extract(url, client)
            with self._lock:
                self._store(key, result, seq)
            return result

        with self._lock:
            hit = self._lookup(key)
            if hit is not None:
                return hit
            entry = self._inflight.get(key)
            if entry is not None:
                entry.waiters += 1
                leader = False
            else:
                entry = _Inflight()
                self._inflight[key] = entry
                self._seq += 1
                seq = self._seq
                leader = True

        if not leader:
            entry.event.wait()
            if entry.error is not None:
                raise entry.error
            assert entry.result is not None
            return entry.result

        try:
            result = self._extract(url, client)
        except BaseException as exc:
            entry.error = exc
            raise
        else:
            entry.result = result
            with self._lock:
                # invalidate가 그 사이에 불렀다면 낡은 결과이므로 저장하지 않는다.
                if self._inflight.get(key) is entry:
                    self._store(key, result, seq)
            return result
        finally:
            with self._lock:
                if self._inflight.get(key) is entry:
                    del self._inflight[key]
            entry.event.set()

    def invalidate(self, url: str, client: str | None = None) -> None:
        """이 키의 캐시를 버린다(403을 낸 URL이 다음 재생에 다시 나오지 않게)."""
        key = (url, client)
        with self._lock:
            self._entries.pop(key, None)
            self._inflight.pop(key, None)

    # ── 내부(락을 쥔 채 부른다) ───────────────────────────────────
    def _lookup(self, key) -> dict | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        info, deadline, _seq = entry
        if self._now() >= deadline:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return info

    def _ttl(self, info: dict) -> float:
        expire = _expire_epoch(info)
        if expire is None:
            return self._max_ttl
        return min(expire - self._wall() - self._margin, self._max_ttl)

    def _store(self, key, info: dict, seq: int) -> None:
        current = self._entries.get(key)
        if current is not None and current[2] > seq:
            return   # 더 늦게 시작한(=더 새) 결과가 이미 있다
        ttl = self._ttl(info)
        if ttl <= 0:
            self._entries.pop(key, None)
            return
        self._entries[key] = (info, self._now() + ttl, seq)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
