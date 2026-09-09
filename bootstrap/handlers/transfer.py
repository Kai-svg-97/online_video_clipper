"""라이브러리 가져오기/내보내기 유스케이스 조립(카테고리 단위 zip 패키지).

zip 입출력은 `ILibraryPackageWriter`/`Reader` 포트 구현이 전담하므로 application
레이어는 THUMBNAIL_DIR 절대경로를 모른다 — 그 경계를 여기서 잇는다.
"""

from __future__ import annotations

from application.transfer.commands import (
    DetectImportConflictsHandler,
    ExportLibraryHandler,
    ImportLibraryHandler,
    PreviewImportHandler,
)
from infrastructure.transfer.portable_package import (
    ZipLibraryPackageReader,
    ZipLibraryPackageWriter,
)

from bootstrap.context import Repositories, Services, TransferHandlers


def build(repos: Repositories, services: Services) -> TransferHandlers:
    writer = ZipLibraryPackageWriter()
    reader = ZipLibraryPackageReader()
    video, song = repos.video, repos.song
    return TransferHandlers(
        export=ExportLibraryHandler(video, song, writer),
        preview=PreviewImportHandler(reader),
        detect_conflicts=DetectImportConflictsHandler(video, song, reader),
        do_import=ImportLibraryHandler(video, song, services.event_bus, reader),
    )
