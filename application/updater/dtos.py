"""업데이트 관련 DTO — GUI 레이어로 넘기는 데이터 계약."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateDTO:
    version: str         # '1.0.1'  (v 접두사 없음)
    asset_name: str      # 'YouTubeContentManager-setup.exe'
    download_url: str
    size_bytes: int
    sha256: str | None   # SHA-256 체크섬 (있으면 검증, 없으면 설치 거부)
    release_notes: str   # GitHub Release 본문 (Markdown)
