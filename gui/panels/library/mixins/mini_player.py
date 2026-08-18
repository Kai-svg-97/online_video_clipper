"""MiniPlayerMixin — 상세를 떠나도 재생을 이어 가는 '지금 재생 중' 상태.

지금까지는 상세 화면을 벗어나면 `stop_player()`가 재생을 끊었다. 노래를 듣다가 다른
카테고리를 둘러보려면 소리가 멈췄고, 돌아와도 처음부터였다.

**재생 중일 때만** 플레이어를 살려 둔 채 화면만 목록으로 되돌리고, 무엇이 재생 중인지는
메인 창 하단의 `MiniPlayerBar`가 보여 준다. 멈춰 있었다면 예전처럼 정지한다 —
안 보이는 곳에서 소리 없이 자원만 붙들고 있을 이유가 없다.

핵심은 **플레이어를 옮기지 않는다**는 것이다. `VideoDetailWidget`은 `_nav_stack`에
그대로 살아 있는 위젯이라, 화면을 목록(0)으로 바꿔도 `QMediaPlayer`는 계속 재생한다.
그래서 복귀는 다시 불러오는 게 아니라 **스택 인덱스만 1로 되돌리는 일**이고, 그 덕에
재생이 한 번도 끊기지 않는다(위치·화질·자막 상태까지 그대로다).

위치·재생 여부는 신호로 밀어 올리지 않고 **0.5초 타이머로 훑는다** — 플레이어가
`positionChanged`를 초당 수십 번 쏘는데 미니바는 그만큼 자주 갱신할 이유가 없다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer

logger = logging.getLogger(__name__)

_TICK_MS = 500


class MiniPlayerMixin:
    """'지금 재생 중' 미니바의 상태 소유자.

    LibraryPanel에 섞여 들어가며 `_detail_widget`·`_nav_stack`을 그대로 쓴다.
    바깥(MainWindow)은 `now_playing_changed`/`now_playing_progress`만 보고 띠를 그린다.
    """

    # ── 진입/해제 ───────────────────────────────────────────────────────
    def _init_mini_player(self) -> None:
        self._now_playing: dict | None = None
        self._mini_related: list = []
        self._mini_related_header: str | None = None
        self._mini_timer = QTimer(self)
        self._mini_timer.setInterval(_TICK_MS)
        self._mini_timer.timeout.connect(self._tick_mini_player)

    def _enter_mini_player(self) -> None:
        """상세를 떠나며 재생을 이어 간다(재생 중일 때만 호출된다)."""
        info = self._detail_info_for_mini()
        if info is None:
            self._detail_widget.stop_player()
            return
        self._now_playing = info
        self.now_playing_changed.emit(dict(info))
        self._mini_timer.start()

    def _clear_mini_player(self, stop: bool = True) -> None:
        """미니바를 거둔다. stop=False면 재생은 건드리지 않는다(상세로 복귀 등)."""
        was_active = self._now_playing is not None
        self._now_playing = None
        self._mini_timer.stop()
        if stop:
            self._detail_widget.stop_player()
        if was_active:
            self.now_playing_changed.emit(None)

    def _detail_info_for_mini(self) -> dict | None:
        """미니바에 표시할 현재 재생 정보(모르면 None)."""
        payload = self._current_detail_payload
        if payload is None:
            return None
        return {
            "payload": payload,
            "title": self._mini_title,
            "subtitle": self._mini_subtitle,
            "poster": self._mini_poster,
            "has_next": self._detail_widget.next_payload() is not None,
        }

    # ── 주기 갱신 ───────────────────────────────────────────────────────
    def _tick_mini_player(self) -> None:
        if self._now_playing is None:
            self._mini_timer.stop()
            return
        try:
            playing = self._detail_widget.is_playing()
            position = self._detail_widget.player_position_ms()
            duration = self._detail_widget.player_duration_ms()
        except RuntimeError:
            logger.debug("미니바 갱신 중 플레이어가 사라짐 — 띠를 닫는다")
            self._clear_mini_player(stop=False)
            return
        self.now_playing_progress.emit(position, duration, playing)

    # ── 미니바 조작 (MainWindow가 연결) ──────────────────────────────────
    def mini_toggle_play(self) -> None:
        if self._now_playing is None:
            return
        self._detail_widget.toggle_play()
        self._tick_mini_player()   # 버튼 모양(▶/⏸)이 즉시 따라오게

    def mini_seek(self, ms: int) -> None:
        if self._now_playing is not None:
            self._detail_widget.seek_to_ms(ms)

    def mini_next(self) -> None:
        """⏭ — 재생목록의 다음 항목으로(화면은 목록에 머문다)."""
        if self._now_playing is None:
            return
        payload = self._detail_widget.next_payload()
        if payload is not None:
            self._on_play_next(payload)

    def mini_open(self) -> None:
        """띠를 클릭 — 보던 상세 화면으로 그대로 돌아간다.

        위젯을 언로드하지 않았으므로 **다시 불러오지 않는다** — 스택만 되돌리면
        재생이 끊기지 않고 위치·자막·화질이 그대로 이어진다.
        """
        if self._now_playing is None:
            return
        self._push_nav_state()
        self._nav_stack.setCurrentIndex(1)
        self._clear_mini_player(stop=False)

    def mini_close(self) -> None:
        """✕ — 재생을 멈추고 띠를 닫는다."""
        self._clear_mini_player(stop=True)

    def _play_next_in_mini(self, payload) -> None:
        """미니바 재생 중의 자동 다음곡 — 화면은 목록에 둔 채 다음 항목을 재생한다.

        연관 목록(재생목록)을 그대로 넘겨야 그다음 곡으로도 계속 이어진다 —
        `related=None`으로 열면 지금 보고 있는 카테고리 목록으로 갈아타 버린다.
        """
        from uuid import UUID  # noqa: PLC0415

        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        related, header = self._mini_related, self._mini_related_header
        if isinstance(payload, UUID):
            self._open_detail(payload, autoplay=True, push_nav=False,
                              related=related, header=header, stay_on_list=True)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload, autoplay=True, push_nav=False,
                                     related=related, header=header, stay_on_list=True)

    def _refresh_mini_track(self) -> None:
        """재생 중인 곡이 바뀌었을 때 띠의 표시를 갈아 끼운다."""
        info = self._detail_info_for_mini()
        if info is None:
            return
        self._now_playing = info
        self.now_playing_changed.emit(dict(info))
        if not self._mini_timer.isActive():
            self._mini_timer.start()

    # ── 재생 정보 기록 (상세를 열 때 호출) ───────────────────────────────
    def _remember_related_for_mini(self, related: list, header: str | None) -> None:
        """미니바 자동 다음곡이 이어 갈 재생목록을 기억한다(상세를 열 때)."""
        self._mini_related = list(related or [])
        self._mini_related_header = header

    def _remember_now_playing(
        self, title: str, subtitle: str = "", poster=None
    ) -> None:
        """상세를 열 때 미니바에 쓸 표시 정보를 챙겨 둔다.

        떠날 때 DB를 다시 뒤지지 않기 위해서다(스트리밍 영상은 조회할 DB도 없다).
        """
        self._mini_title = title or ""
        self._mini_subtitle = subtitle or ""
        self._mini_poster = poster
