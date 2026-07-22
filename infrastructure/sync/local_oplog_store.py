"""로컬 op 로그 세그먼트 저장 (IOplogStore의 로컬 구현).

레이아웃: <base>/<install_id>/NNNNNN.ndjson  (append-only, seq 단조증가, 한 줄=한 op).
각 기기는 자기 install_id 폴더에만 쓰므로 파일 쓰기 경합이 없다. 원격 업로드는
cloud_oplog_store(Phase 4)가 담당하며 동일한 파일 규약을 쓴다.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from domain.sync.value_objects import Op

logger = logging.getLogger(__name__)


class LocalOplogStore:
    """IOplogStore를 구조적으로 만족(로컬 pending 세그먼트)."""

    def __init__(self, base_dir: Path, install_id: str) -> None:
        self._base = Path(base_dir)
        self._install = install_id

    def _dir(self, install_id: str) -> Path:
        return self._base / install_id

    def append(self, ops: list[Op]) -> int:
        """새 세그먼트에 ops를 기록하고 그 seq를 반환한다. 원자적(tmp→rename)."""
        if not ops:
            return self.head_seq(self._install)
        d = self._dir(self._install)
        d.mkdir(parents=True, exist_ok=True)
        seq = self.head_seq(self._install) + 1
        tmp = d / f"{seq:06d}.ndjson.tmp"
        final = d / f"{seq:06d}.ndjson"
        with open(tmp, "w", encoding="utf-8") as f:
            for op in ops:
                f.write(json.dumps(op.to_dict(), ensure_ascii=False) + "\n")
        os.replace(tmp, final)
        return seq

    def _segments(self, install_id: str) -> list[tuple[int, Path]]:
        d = self._dir(install_id)
        if not d.is_dir():
            return []
        segs = [
            (int(p.stem), p)
            for p in d.iterdir()
            if p.suffix == ".ndjson" and p.stem.isdigit()
        ]
        return sorted(segs)

    def head_seq(self, install_id: str) -> int:
        segs = self._segments(install_id)
        return segs[-1][0] if segs else 0

    def read_segment(self, install_id: str, seq: int) -> list[Op]:
        """단일 세그먼트의 op 목록을 반환한다(없으면 빈 리스트)."""
        path = self._dir(install_id) / f"{seq:06d}.ndjson"
        if not path.is_file():
            return []
        ops: list[Op] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ops.append(Op.from_dict(json.loads(line)))
        return ops

    def read_since(self, install_id: str, after_seq: int) -> list[Op]:
        ops: list[Op] = []
        for seq, path in self._segments(install_id):
            if seq <= after_seq:
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ops.append(Op.from_dict(json.loads(line)))
        return ops

    def list_installs(self) -> dict[str, int]:
        if not self._base.is_dir():
            return {}
        out: dict[str, int] = {}
        for d in self._base.iterdir():
            if d.is_dir():
                head = self.head_seq(d.name)
                if head:
                    out[d.name] = head
        return out
