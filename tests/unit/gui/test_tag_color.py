"""태그·카테고리 색상 배정이 실행 간 안정적인지 검증한다.

기존 구현은 `hash(name) % len(_TAG_PALETTE)`를 썼는데, 파이썬 str 해시는
PYTHONHASHSEED로 프로세스마다 무작위화되므로 앱을 다시 켤 때마다 색이 바뀌었다.
"""
from __future__ import annotations

import subprocess
import sys

from gui.panels.library_panel import _TAG_PALETTE, tag_color


class TestTagColor:
    def test_returns_palette_color(self):
        assert tag_color("music") in _TAG_PALETTE

    def test_deterministic_within_process(self):
        assert tag_color("music") == tag_color("music")

    def test_different_names_can_differ(self):
        """32색 팔레트이므로 몇 개 이름은 서로 다른 색을 받아야 한다."""
        names = ["music", "AI Coding", "Obsidian", "Redis", "Servers", "Movies"]
        assert len({tag_color(n) for n in names}) > 1

    def test_handles_korean_and_empty(self):
        assert tag_color("바이브코딩") in _TAG_PALETTE
        assert tag_color("") in _TAG_PALETTE

    def test_stable_across_processes(self):
        """핵심 회귀 — 별도 프로세스(다른 해시 시드)에서도 같은 색이어야 한다."""
        code = (
            "from gui.panels.library_panel import tag_color; "
            "print(','.join(tag_color(n) for n in ['music', 'AI Coding', '바이브코딩']))"
        )
        runs = set()
        for _ in range(3):
            out = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, check=True, encoding="utf-8",
            )
            runs.add(out.stdout.strip())
        assert len(runs) == 1, f"실행마다 색이 달라짐: {runs}"
