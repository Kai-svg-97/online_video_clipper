"""VideoSubtitleMixin — 영상 자막(YouTube 캡션) 두 칸의 목록·선택·번역·내려받기.

    InlinePlayer에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다 — 조립은 `gui/widgets/video_player.py`).
"""
from __future__ import annotations

import logging

from config import settings
from gui.text import tr
from gui.widgets.player.stream import _SubtitleFetchWorker, _SubtitleListWorker, _VSUB_LIST_CACHE
from gui.widgets.subtitle_track import SubtitleTrack
from gui.workers import retire_thread, track_thread

logger = logging.getLogger(__name__)


class VideoSubtitleMixin:
    """가사 자막과 별개 기능. 네트워크는 QThread에서만 한다(gui/workers.py 규칙)."""

    def _apply_video_subtitle_position(self, pos_ms: int) -> None:
        """두 칸의 현재 자막을 함께 갱신한다(내용이 바뀔 때만 다시 그린다)."""
        if not any(self._vsub_tracks):
            return
        texts = tuple(
            (track.text_at(pos_ms) if track is not None else "")
            for track in self._vsub_tracks
        )
        if texts == self._vsub_texts:
            return
        self._vsub_texts = texts
        for overlay in self._all_subtitles():
            overlay.set_subtitle_texts(*texts)

    def _load_video_subtitle_list(self) -> None:
        """이 영상이 제공하는 자막 목록을 백그라운드로 조회한다(캐시 있으면 즉시)."""
        url = self._video_url
        if not url or self._subtitles is None:
            return
        cached = _VSUB_LIST_CACHE.get(url)
        if cached is not None:
            self._on_video_subtitle_list(url, cached)
            return
        worker = _SubtitleListWorker(
            self._subtitles, url, self._cookie_opts_for_subtitles(),
            info_source=self._info_source,
        )
        worker.done.connect(self._on_video_subtitle_list)
        worker.finished.connect(lambda w=worker: retire_thread(w, "done"))
        track_thread(worker)
        self._vsub_list_worker = worker
        worker.start()

    def _translate_targets_source(self):
        """컨트롤바가 자동 번역 메뉴를 열 때 부를 함수(자막 소스가 없으면 None)."""
        return self._subtitles.translate_targets if self._subtitles is not None else None

    def _cookie_opts_for_subtitles(self) -> dict:
        """자막 조회용 yt-dlp 옵션(쿠키 등). 없으면 익명으로 — 자막은 대개 공개다."""
        return dict(getattr(self, "_ydl_opts", None) or {})

    def _on_video_subtitle_list(self, url: str, tracks: list) -> None:
        if url != self._video_url:
            return   # 그 사이 다른 영상으로 넘어갔다
        _VSUB_LIST_CACHE[url] = tracks
        self._vsub_available = tracks
        for bar in self._all_bars():
            bar.set_video_subtitle_tracks(tracks)
        self._restore_preferred_subtitles()

    def _restore_preferred_subtitles(self) -> None:
        """지난번에 고른 언어가 이 영상에도 있으면 자동으로 켠다.

        영상마다 다시 고르게 하면 두 줄 자막처럼 '늘 쓰는 설정'이 매번 사라진다.
        """
        for slot in (0, 1):
            lang = self._vsub_pref_lang[slot]
            if not lang:
                continue
            track = next((t for t in self._vsub_available if t.lang == lang), None)
            if track is not None:
                self._select_video_subtitle(slot, track.key, save=False)

    def _select_video_subtitle(self, slot: int, key: str, save: bool = True) -> None:
        """칸 하나의 트랙을 고른다(key가 비면 끈다)."""
        if slot not in (0, 1):
            return
        if not key:
            self._vsub_keys[slot] = ""
            self._vsub_tracks[slot] = None
            self._vsub_texts = ("", "")
            for bar in self._all_bars():
                bar.set_video_subtitle_selection(slot, "", self._vsub_langs[slot])
            for overlay in self._all_subtitles():
                overlay.set_subtitle_texts(*self._vsub_texts)
            if save:
                self._save_subtitle_pref(slot, "")
            return
        base = next((t for t in self._vsub_available if t.key == key), None)
        if base is None:
            return
        self._vsub_keys[slot] = key
        for bar in self._all_bars():
            bar.set_video_subtitle_selection(slot, key, self._vsub_langs[slot])
        if save:
            self._save_subtitle_pref(slot, base.lang)
        self._fetch_video_subtitle(slot, base)

    def _translate_video_subtitle(self, slot: int, lang: str) -> None:
        """칸 하나의 자동 번역 대상을 바꾼다(빈 값이면 원본)."""
        if slot not in (0, 1):
            return
        self._vsub_langs[slot] = lang or ""
        for bar in self._all_bars():
            bar.set_video_subtitle_selection(slot, self._vsub_keys[slot], self._vsub_langs[slot])
        key = self._vsub_keys[slot]
        if not key:
            # 아직 언어를 고르지 않았다면 첫 트랙(자동 생성 우선)에 번역을 건다 —
            # '번역만 골랐는데 아무 일도 없다'가 되지 않도록.
            base = next((t for t in self._vsub_available if t.auto), None)                 or (self._vsub_available[0] if self._vsub_available else None)
            if base is None:
                return
            self._select_video_subtitle(slot, base.key)
            return
        base = next((t for t in self._vsub_available if t.key == key), None)
        if base is not None:
            self._fetch_video_subtitle(slot, base)

    def _fetch_video_subtitle(self, slot: int, base) -> None:
        """자막 파일을 백그라운드로 받아 트랙으로 만든다."""
        if self._subtitles is None:
            return
        lang = self._vsub_langs[slot]
        track_info = self._subtitles.translated(base, lang) if lang else base
        self._status_lbl.setText(tr("자막을 받는 중…"))
        self._status_lbl.show()
        self._start_subtitle_fetch(slot, track_info)

    def _start_subtitle_fetch(self, slot: int, track_info) -> None:
        """자막 내려받기 워커를 띄운다(테스트가 여기만 가로채면 네트워크가 없다)."""
        worker = _SubtitleFetchWorker(self._subtitles, slot, track_info)
        worker.done.connect(self._on_video_subtitle_cues)
        worker.finished.connect(lambda w=worker: retire_thread(w, "done"))
        track_thread(worker)
        self._vsub_workers[slot] = worker
        worker.start()

    def _on_video_subtitle_cues(self, slot: int, key: str, cues: list) -> None:
        if slot not in (0, 1) or key != self._vsub_keys[slot]:
            return   # 그 사이 다른 트랙을 골랐다
        self._status_lbl.hide()
        if not cues:
            self._show_transient(tr("자막을 가져오지 못했습니다"), 2500)
            return
        self._vsub_tracks[slot] = SubtitleTrack.from_tuples(cues)
        self._vsub_texts = ("", "")   # 강제 갱신
        self._apply_video_subtitle_position(self._player.position())
        # 이미 받은 큐다 — 검색 색인에 그대로 넘긴다. 이 경로가 없으면 자막 색인은
        # 사용자가 상세화면에서 따로 눌러야만 쌓인다.
        base = next((t for t in self._vsub_available if t.key == key), None)
        self.subtitle_cues_ready.emit(
            self._vsub_langs[slot] or getattr(base, "lang", "") or "",
            getattr(base, "label", "") or "",
            cues,
        )

    def _save_subtitle_pref(self, slot: int, lang: str) -> None:
        self._vsub_pref_lang[slot] = lang
        try:
            settings.save_setting(f"video_subtitle_lang_{slot + 1}", lang)
        except Exception:
            logger.exception("자막 언어 설정 저장 실패")

    def _clear_video_subtitles(self) -> None:
        """다른 영상으로 넘어갈 때 — 이전 영상의 자막이 남지 않게 한다."""
        self._vsub_available = []
        self._vsub_keys = ["", ""]
        self._vsub_tracks = [None, None]
        self._vsub_texts = ("", "")
        for bar in self._all_bars():
            bar.set_video_subtitle_tracks([])
            for slot in (0, 1):
                bar.set_video_subtitle_selection(slot, "", self._vsub_langs[slot])
        for overlay in self._all_subtitles():
            overlay.set_subtitle_texts("", "")
