"""yt-dlp JS 런타임 옵션 헬퍼 시험.

YouTube 챌린지는 JS 런타임이 있어야 풀린다 — 없으면 대체 클라이언트로 밀려
고화질·먼 seek이 403으로 막힌다.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from utils import ytdlp_runtime
from utils.ytdlp_runtime import js_runtime_opts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clear_cache():
    js_runtime_opts.cache_clear()
    yield
    js_runtime_opts.cache_clear()


def _no_bundle(monkeypatch):
    class _Missing:
        def exists(self):
            return False

    monkeypatch.setattr(ytdlp_runtime, "get_resource_path", lambda rel: _Missing())


def test_node만_있으면_node를_준다(monkeypatch):
    _no_bundle(monkeypatch)
    monkeypatch.setattr(
        ytdlp_runtime.shutil, "which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    opts = js_runtime_opts()
    assert list(opts["js_runtimes"]) == ["node"]
    assert opts["js_runtimes"]["node"].get("path") == "/usr/bin/node"


def test_아무것도_없으면_빈_dict와_경고(monkeypatch, caplog):
    _no_bundle(monkeypatch)
    monkeypatch.setattr(ytdlp_runtime.shutil, "which", lambda name: None)
    with caplog.at_level(logging.WARNING, logger="utils.ytdlp_runtime"):
        assert js_runtime_opts() == {}
        assert js_runtime_opts() == {}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1  # 캐시되므로 한 번만


def test_번들_deno가_있으면_path가_들어간다(monkeypatch, tmp_path):
    exe = tmp_path / "deno.exe"
    exe.write_text("")

    class _Found:
        def __init__(self, p):
            self._p = p

        def exists(self):
            return self._p.exists()

        def __str__(self):
            return str(self._p)

    monkeypatch.setattr(
        ytdlp_runtime, "get_resource_path",
        lambda rel: _Found(exe if rel in ("bin/deno.exe", "bin/deno") else tmp_path / "x"),
    )
    monkeypatch.setattr(ytdlp_runtime.shutil, "which", lambda name: None)
    opts = js_runtime_opts()
    assert opts["js_runtimes"]["deno"]["path"] == str(exe)


def test_deno가_node보다_먼저다(monkeypatch):
    _no_bundle(monkeypatch)
    monkeypatch.setattr(ytdlp_runtime.shutil, "which", lambda name: f"/bin/{name}")
    assert list(js_runtime_opts()["js_runtimes"])[0] == "deno"


def _uses_ytdl(tree: ast.AST) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "YoutubeDL":
                return True
    return False


def _uses_helper(tree: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id == "js_runtime_opts"
        or isinstance(n, ast.Attribute) and n.attr == "js_runtime_opts"
        for n in ast.walk(tree)
    )


def test_YoutubeDL을_부르는_모든_파일이_js_runtime_opts를_쓴다():
    missing = []
    for top in ("application", "infrastructure", "gui"):
        for p in (ROOT / top).rglob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            if _uses_ytdl(tree) and not _uses_helper(tree):
                missing.append(str(p.relative_to(ROOT)))
    assert not missing, f"js_runtime_opts 누락: {missing}"
