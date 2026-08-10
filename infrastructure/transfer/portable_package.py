"""포터블 라이브러리 패키지(zip) 읽기/쓰기 — domain.shared.ports의
`ILibraryPackageWriter`/`ILibraryPackageReader`를 구조적으로 만족한다.

패키지 구조:
    manifest.json          # {"format_version", "app_version", "exported_at", "video_count", ...}
    data.json              # {"categories": [...], "videos": [...]}
    thumbnails/<name>      # data["videos"][i]["thumbnail_rel"]로 참조되는 실제 파일

값 해석(THUMBNAIL_DIR 절대경로 결합)은 여기서만 한다 — application 레이어는
`thumbnail_path`(DB에 저장된 THUMBNAIL_DIR 기준 상대경로)만 알고 절대경로를 모른다.
"""
from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from uuid import UUID

from config import settings

logger = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.json"
_DATA_NAME = "data.json"
_THUMB_PREFIX = "thumbnails/"


class ZipLibraryPackageWriter:
    """라이브러리 내보내기 — zip 파일 하나로 묶는다."""

    def write(self, dest_path: str, manifest: dict, data: dict) -> None:
        videos = data.get("videos", [])
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for video in videos:
                rel = self._include_thumbnail(zf, video.get("thumbnail_path", ""))
                if rel:
                    video["thumbnail_rel"] = rel
            zf.writestr(_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr(_DATA_NAME, json.dumps(data, ensure_ascii=False, indent=2))

    def _include_thumbnail(self, zf: zipfile.ZipFile, thumbnail_path: str) -> str | None:
        if not thumbnail_path:
            return None
        src = Path(settings.THUMBNAIL_DIR) / thumbnail_path
        if not src.is_file():
            logger.warning("내보내기: 썸네일 파일을 찾을 수 없어 건너뜀: %s", src)
            return None
        rel_name = f"{src.stem}_{abs(hash(thumbnail_path)) % 1_000_000:06d}{src.suffix}"
        arcname = _THUMB_PREFIX + rel_name
        # 이미 같은 이름으로 담겨 있으면(썸네일 재사용) 다시 쓰지 않는다.
        if arcname not in zf.namelist():
            zf.write(src, arcname)
        return rel_name


class ZipLibraryPackageReader:
    """라이브러리 가져오기 — zip에서 manifest/data를 읽고 썸네일을 로컬로 복사한다."""

    def read(self, src_path: str) -> tuple[dict, dict]:
        with zipfile.ZipFile(src_path) as zf:
            manifest = json.loads(zf.read(_MANIFEST_NAME).decode("utf-8"))
            data = json.loads(zf.read(_DATA_NAME).decode("utf-8"))
        return manifest, data

    def import_thumbnail(self, src_path: str, thumbnail_rel: str, video_id: UUID) -> str | None:
        if not thumbnail_rel:
            return None
        arcname = _THUMB_PREFIX + thumbnail_rel
        try:
            with zipfile.ZipFile(src_path) as zf:
                if arcname not in zf.namelist():
                    return None
                raw = zf.read(arcname)
        except (OSError, KeyError):
            logger.exception("가져오기: 패키지 썸네일 읽기 실패: %s", arcname)
            return None
        suffix = Path(thumbnail_rel).suffix or ".jpg"
        dest_rel = f"{video_id}{suffix}"
        dest_abs = Path(settings.THUMBNAIL_DIR) / dest_rel
        try:
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            dest_abs.write_bytes(raw)
        except OSError:
            logger.exception("가져오기: 썸네일 저장 실패: %s", dest_abs)
            return None
        return dest_rel
