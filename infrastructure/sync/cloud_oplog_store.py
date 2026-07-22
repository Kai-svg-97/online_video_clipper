"""원격 op 로그 저장 (IOplogStore over ICloudSyncProvider).

레이아웃(원격): oplog/<install>/<seq6>.ndjson + oplog/installs.json(레지스트리).
op 세그먼트는 소형 텍스트라 provider.read_text/write_text로 다룬다(미디어만 upload/download).
"""

from __future__ import annotations

import json
import logging

from domain.sync.value_objects import Op

logger = logging.getLogger(__name__)

_ROOT = "oplog"
_REGISTRY = "oplog/installs.json"


class CloudOplogStore:
    def __init__(self, provider) -> None:
        self._p = provider  # ICloudSyncProvider

    @staticmethod
    def _seg_path(install_id: str, seq: int) -> str:
        return f"{_ROOT}/{install_id}/{seq:06d}.ndjson"

    def put_ops(self, install_id: str, seq: int, ops: list[Op]) -> None:
        text = "\n".join(json.dumps(o.to_dict(), ensure_ascii=False) for o in ops)
        self._p.write_text(self._seg_path(install_id, seq), text)

    def list_installs(self) -> dict[str, int]:
        """{install_id: head_seq} — 원격 세그먼트를 훑어 집계."""
        out: dict[str, int] = {}
        for rf in self._p.list_files(f"{_ROOT}/"):
            parts = rf.path.split("/")
            if len(parts) >= 3 and parts[0] == _ROOT and parts[-1].endswith(".ndjson"):
                stem = parts[-1][: -len(".ndjson")]
                if stem.isdigit():
                    install = parts[1]
                    out[install] = max(out.get(install, 0), int(stem))
        return out

    def read_since(self, install_id: str, after_seq: int) -> list[Op]:
        seqs: list[int] = []
        for rf in self._p.list_files(f"{_ROOT}/{install_id}/"):
            stem = rf.path.split("/")[-1]
            if stem.endswith(".ndjson"):
                s = stem[: -len(".ndjson")]
                if s.isdigit() and int(s) > after_seq:
                    seqs.append(int(s))
        ops: list[Op] = []
        for seq in sorted(seqs):
            text = self._p.read_text(self._seg_path(install_id, seq)) or ""
            for line in text.splitlines():
                line = line.strip()
                if line:
                    ops.append(Op.from_dict(json.loads(line)))
        return ops

    def read_registry(self) -> dict[str, int]:
        txt = self._p.read_text(_REGISTRY)
        if not txt:
            return {}
        try:
            return {k: int(v) for k, v in json.loads(txt).items()}
        except Exception:
            logger.exception("installs.json 파싱 실패")
            return {}

    def write_registry(self, registry: dict[str, int]) -> None:
        self._p.write_text(_REGISTRY, json.dumps(registry, ensure_ascii=False))
