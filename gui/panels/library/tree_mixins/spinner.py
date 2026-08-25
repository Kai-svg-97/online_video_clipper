"""트리 노드 로딩 스피너 — 노드 텍스트 뒤에 회전 문자를 덧붙인다.

원래 텍스트는 `_ORIG_TEXT_ROLE`에 보관한다. 그래서 델리게이트는 텍스트를 파싱하지
않고 롤만 읽는다(스피너가 붙은 텍스트를 파싱하면 이름이 깨진다).
"""
from __future__ import annotations

from PyQt6.QtWidgets import QTreeWidgetItem

from gui.panels.library.constants import _ORIG_TEXT_ROLE


class _TreeSpinnerMixin:
    """노드별 로딩 스피너 표시/해제."""

    def set_node_loading(self, key: str, item: "QTreeWidgetItem | None", loading: bool) -> None:
        """지정 키 노드의 로딩 스피너를 시작/종료한다."""
        if key in self._spinner_items:
            old_item = self._spinner_items.pop(key)
            self._spinner_frame_idx.pop(key, None)
            orig = old_item.data(0, _ORIG_TEXT_ROLE)
            if orig is not None:
                old_item.setText(0, orig)
                old_item.setData(0, _ORIG_TEXT_ROLE, None)
        if loading and item is not None:
            self._spinner_items[key] = item
            self._spinner_frame_idx[key] = 0
            item.setData(0, _ORIG_TEXT_ROLE, item.text(0))
            self._update_spinner_text(key)
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        if not self._spinner_items:
            self._spinner_timer.stop()

    def _clear_all_spinners(self) -> None:
        """load() 전 모든 스피너를 안전하게 정리한다 (clear() 후 해제된 Qt 객체 참조 방지)."""
        for item in self._spinner_items.values():
            orig = item.data(0, _ORIG_TEXT_ROLE)
            if orig is not None:
                item.setText(0, orig)
                item.setData(0, _ORIG_TEXT_ROLE, None)
        self._spinner_items.clear()
        self._spinner_frame_idx.clear()
        self._spinner_timer.stop()

    def _tick_spinner(self) -> None:
        if not self._spinner_items:
            self._spinner_timer.stop()
            return
        for key in list(self._spinner_items):
            self._spinner_frame_idx[key] = (self._spinner_frame_idx.get(key, 0) + 1) % len(self._spinner_frames)
            self._update_spinner_text(key)

    def _update_spinner_text(self, key: str) -> None:
        item = self._spinner_items.get(key)
        if item is None:
            return
        orig = item.data(0, _ORIG_TEXT_ROLE)
        if orig is None:
            return
        frame = self._spinner_frames[self._spinner_frame_idx.get(key, 0)]
        item.setText(0, f"{orig}  {frame}")
