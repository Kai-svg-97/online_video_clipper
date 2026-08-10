"""라이브러리 가져오기/내보내기 — 카테고리 선택 내보내기, 미리보기·충돌감지·병합 가져오기.

카테고리/영상/노래(가사·싱크) 정보를 자기완결적 zip 패키지로 옮긴다. 실제 파일
입출력은 `domain.shared.ports.ILibraryPackageWriter`/`ILibraryPackageReader`
(구현: `infrastructure.transfer.portable_package`)에 위임하고, 이 모듈은 순수하게
어떤 데이터를 담을지·병합 규칙만 다룬다.

병합 키:
- 영상 = URL(`IVideoRepository.get_by_url`) — 카테고리/제목이 달라도 같은 영상으로 본다.
- 카테고리 = (이름, 로컬로 매핑된 부모 id) — 패키지 안의 카테고리 id는 그 패키지
  안에서만 의미 있는 문자열 키이고, 가져오기 시 이름+부모 경로가 같은 로컬
  카테고리가 있으면 새로 만들지 않고 그걸 재사용한다.

충돌 판정: 존재하는 영상과 값이 다른 필드만 "충돌"로 보고한다. 한쪽이 비어있고
다른 쪽이 채워져 있으면 채워진 쪽을 기본 선택값으로 제시한다(빈 칸 채우기는
사용자 확인 없이도 안전하다는 가정) — 둘 다 채워져 있는데 다르면 기존값을
기본으로 두어 조용한 덮어쓰기를 막는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category
from domain.library.repositories import IVideoRepository, SearchQuery
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from domain.shared.ports import IEventBus, ILibraryPackageReader, ILibraryPackageWriter
from domain.song.aggregates import SongInfoAggregate
from domain.song.repositories import ISongRepository
from domain.song.value_objects import LyricsLine, SongSourceRef

from application.transfer.dtos import (
    ExportResultDTO,
    ImportConflictDTO,
    ImportConflictsDTO,
    ImportCategoryOptionDTO,
    ImportFieldDiffDTO,
    ImportPreviewDTO,
    ImportResultDTO,
)

_FIELD_LABELS = {
    "title": "제목",
    "notes": "메모",
    "description": "설명",
    "category": "카테고리",
    "artist": "가수",
    "album": "앨범",
    "song_title": "노래 제목",
    "release_year": "발매년도",
    "lyrics": "가사",
    "lyrics_offset_ms": "가사 싱크 오프셋",
}

_SONG_TEXT_FIELDS = ("artist", "album", "song_title", "release_year")


# ── 내보내기 ──────────────────────────────────────────────────────────────

@dataclass
class ExportLibraryCommand:
    category_ids: list[UUID]      # 사용자가 고른 로컬 카테고리(하위 카테고리는 자동 포함)
    dest_path: str


class ExportLibraryHandler:
    def __init__(
        self, video_repo: IVideoRepository, song_repo: ISongRepository,
        package_writer: ILibraryPackageWriter,
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._writer = package_writer

    def handle(self, cmd: ExportLibraryCommand) -> ExportResultDTO:
        all_cats = {c.id: c for c in self._videos.list_categories()}
        selected = _expand_with_descendants(all_cats, cmd.category_ids)

        cat_payload = [
            {
                "id": str(cid),
                "name": all_cats[cid].name,
                "parent_id": str(all_cats[cid].parent_id)
                if all_cats[cid].parent_id in selected else None,
            }
            for cid in selected
        ]

        tag_names_by_id = {t.id: t.name for t in self._videos.list_tags()}
        videos_payload: list[dict] = []
        for cid in selected:
            query = SearchQuery(category_id=cid, categorized_only=False, limit=1_000_000)
            for summary in self._videos.search(query):
                agg = self._videos.get_by_id(summary.id) or summary
                videos_payload.append(self._video_payload(agg, selected, tag_names_by_id))

        data = {"categories": cat_payload, "videos": videos_payload}
        manifest = {
            "format_version": 1,
            "video_count": len(videos_payload),
            "category_count": len(cat_payload),
        }
        self._writer.write(cmd.dest_path, manifest, data)
        return ExportResultDTO(
            path=cmd.dest_path, category_count=len(cat_payload), video_count=len(videos_payload),
        )

    def _video_payload(self, agg: VideoAggregate, selected: set, tag_names_by_id: dict) -> dict:
        v = agg.video
        payload = {
            "id": str(agg.id),
            "url": str(v.url),
            "title": v.title,
            "channel_name": v.channel.name if v.channel else "",
            "channel_url": v.channel.url if v.channel else "",
            "channel_id": v.channel.channel_id if v.channel else "",
            "duration_sec": v.duration.seconds if v.duration else None,
            "published_at": v.published_at.isoformat() if v.published_at else None,
            "view_count": v.view_count,
            "notes": v.notes,
            "description": v.description,
            "category_id": str(agg.category_id) if agg.category_id in selected else None,
            "tags": [tag_names_by_id[tid] for tid in agg.tag_ids if tid in tag_names_by_id],
            "thumbnail_path": v.thumbnail_path or "",
            "song": self._song_payload(agg.id),
        }
        return payload

    def _song_payload(self, video_id: UUID) -> dict | None:
        song = self._songs.get(video_id)
        if song is None:
            return None
        info = song.info
        return {
            "is_song": info.is_song,
            "artist": info.artist,
            "album": info.album,
            "song_title": info.song_title,
            "release_year": info.release_year,
            "lyrics_language": info.lyrics_language,
            "lyrics_offset_ms": info.lyrics_offset_ms,
            "lyrics_lines": [
                {"original": ln.original, "translation": ln.translation, "start_ms": ln.start_ms}
                for ln in info.lyrics_lines
            ],
            "source_name": info.source.name if info.source else "",
            "source_url": info.source.url if info.source else "",
        }


def _expand_with_descendants(all_cats: dict[UUID, Category], roots: list[UUID]) -> set[UUID]:
    selected: set[UUID] = set()
    stack = [cid for cid in roots if cid in all_cats]
    while stack:
        cid = stack.pop()
        if cid in selected:
            continue
        selected.add(cid)
        stack.extend(c.id for c in all_cats.values() if c.parent_id == cid)
    return selected


# ── 가져오기: 미리보기 ────────────────────────────────────────────────────

@dataclass
class PreviewImportCommand:
    archive_path: str


class PreviewImportHandler:
    def __init__(self, package_reader: ILibraryPackageReader) -> None:
        self._reader = package_reader

    def handle(self, cmd: PreviewImportCommand) -> ImportPreviewDTO:
        _manifest, data = self._reader.read(cmd.archive_path)
        videos = data.get("videos", [])
        counts: dict[str, int] = {}
        for v in videos:
            cid = v.get("category_id")
            if cid:
                counts[cid] = counts.get(cid, 0) + 1
        categories = tuple(
            ImportCategoryOptionDTO(
                id=c["id"], name=c["name"], parent_id=c.get("parent_id"),
                video_count=counts.get(c["id"], 0),
            )
            for c in data.get("categories", [])
        )
        return ImportPreviewDTO(categories=categories, total_video_count=len(videos))


# ── 가져오기: 충돌 감지 ───────────────────────────────────────────────────

@dataclass
class DetectImportConflictsCommand:
    archive_path: str
    category_ids: list[str] = field(default_factory=list)   # 빈 리스트 = 전체


class DetectImportConflictsHandler:
    def __init__(
        self, video_repo: IVideoRepository, song_repo: ISongRepository,
        package_reader: ILibraryPackageReader,
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._reader = package_reader

    def handle(self, cmd: DetectImportConflictsCommand) -> ImportConflictsDTO:
        _manifest, data = self._reader.read(cmd.archive_path)
        pkg_cats_by_id = {c["id"]: c for c in data.get("categories", [])}
        selected = set(cmd.category_ids) or None
        local_cats_by_id = {c.id: c for c in self._videos.list_categories()}

        conflicts: list[ImportConflictDTO] = []
        new_count = 0
        for v in data.get("videos", []):
            if selected is not None and v.get("category_id") not in selected:
                continue
            existing = self._videos.get_by_url(v["url"])
            if existing is None:
                new_count += 1
                continue
            fields = self._diff_fields(existing, v, local_cats_by_id, pkg_cats_by_id)
            if fields:
                conflicts.append(
                    ImportConflictDTO(url=v["url"], title=v.get("title") or v["url"], fields=tuple(fields))
                )
        return ImportConflictsDTO(conflicts=tuple(conflicts), new_video_count=new_count)

    def _diff_fields(self, existing: VideoAggregate, v: dict, local_cats: dict, pkg_cats: dict) -> list:
        existing_song = self._songs.get(existing.id)
        incoming_song = v.get("song") or {}
        ei = existing.video
        ex_offset = existing_song.info.lyrics_offset_ms if existing_song else 0
        in_offset = incoming_song.get("lyrics_offset_ms", 0) or 0

        rows = [
            ("title", ei.title, v.get("title", "") or "",
             bool(ei.title.strip()), bool((v.get("title") or "").strip())),
            ("notes", ei.notes, v.get("notes", "") or "",
             bool(ei.notes.strip()), bool((v.get("notes") or "").strip())),
            ("description", ei.description, v.get("description", "") or "",
             bool(ei.description.strip()), bool((v.get("description") or "").strip())),
            ("category",
             _local_category_path(existing.category_id, local_cats),
             _package_category_path(v.get("category_id"), pkg_cats),
             existing.category_id is not None, bool(v.get("category_id"))),
            *[
                (
                    field, getattr(existing_song.info, field) if existing_song else "",
                    incoming_song.get(field, "") or "",
                    bool(existing_song and getattr(existing_song.info, field).strip()),
                    bool((incoming_song.get(field) or "").strip()),
                )
                for field in _SONG_TEXT_FIELDS
            ],
            ("lyrics",
             _lyrics_preview(existing_song.info.lyrics_lines) if existing_song else "",
             _lyrics_preview_from_dicts(incoming_song.get("lyrics_lines") or []),
             bool(existing_song and existing_song.info.lyrics_lines),
             bool(incoming_song.get("lyrics_lines")),
             ),
            ("lyrics_offset_ms", f"{ex_offset / 1000:+.2f}s", f"{in_offset / 1000:+.2f}s",
             ex_offset != 0, in_offset != 0),
        ]

        result = []
        for key, ex_val, in_val, ex_filled, in_filled in rows:
            if ex_val == in_val:
                continue
            default = "incoming" if (not ex_filled and in_filled) else "existing"
            result.append(ImportFieldDiffDTO(
                field=key, label=_FIELD_LABELS[key],
                existing_value=ex_val, incoming_value=in_val,
                existing_filled=ex_filled, incoming_filled=in_filled,
                default_choice=default,
            ))
        return result


def _local_category_path(cat_id, cats: dict) -> str:
    if cat_id is None:
        return ""
    parts, seen, cur = [], set(), cat_id
    while cur is not None and cur not in seen and cur in cats:
        seen.add(cur)
        parts.append(cats[cur].name)
        cur = cats[cur].parent_id
    return " > ".join(reversed(parts))


def _package_category_path(cat_id, pkg_cats: dict) -> str:
    if not cat_id:
        return ""
    parts, seen, cur = [], set(), cat_id
    while cur and cur not in seen and cur in pkg_cats:
        seen.add(cur)
        parts.append(pkg_cats[cur]["name"])
        cur = pkg_cats[cur].get("parent_id")
    return " > ".join(reversed(parts))


def _lyrics_preview(lines: list[LyricsLine]) -> str:
    texts = [ln.original for ln in lines if ln.original.strip()]
    if not texts:
        return ""
    preview = " / ".join(texts[:2])
    return f"{len(lines)}줄 · {preview}" + ("…" if len(texts) > 2 else "")


def _lyrics_preview_from_dicts(lines: list[dict]) -> str:
    texts = [ln.get("original", "") for ln in lines if (ln.get("original") or "").strip()]
    if not texts:
        return ""
    preview = " / ".join(texts[:2])
    return f"{len(lines)}줄 · {preview}" + ("…" if len(texts) > 2 else "")


# ── 가져오기: 실행 ────────────────────────────────────────────────────────

@dataclass
class ImportLibraryCommand:
    archive_path: str
    category_ids: list[str] = field(default_factory=list)     # 빈 리스트 = 전체
    resolutions: dict[str, dict[str, str]] = field(default_factory=dict)   # {url: {field: "existing"|"incoming"}}


class ImportLibraryHandler:
    def __init__(
        self, video_repo: IVideoRepository, song_repo: ISongRepository,
        event_bus: IEventBus, package_reader: ILibraryPackageReader,
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._bus = event_bus
        self._reader = package_reader

    def handle(self, cmd: ImportLibraryCommand) -> ImportResultDTO:
        _manifest, data = self._reader.read(cmd.archive_path)
        selected = set(cmd.category_ids) or None
        pkg_cats = {
            c["id"]: c for c in data.get("categories", [])
            if selected is None or c["id"] in selected
        }
        pkg_to_local = self._resolve_categories(pkg_cats)

        created = merged = 0
        for v in data.get("videos", []):
            cid = v.get("category_id")
            if selected is not None and cid not in selected:
                continue
            local_cat_id = pkg_to_local.get(cid) if cid else None
            existing = self._videos.get_by_url(v["url"])
            if existing is None:
                self._create_video(v, local_cat_id, cmd.archive_path)
                created += 1
            else:
                self._merge_video(
                    existing, v, local_cat_id,
                    cmd.resolutions.get(v["url"], {}), cmd.archive_path,
                )
                merged += 1
        return ImportResultDTO(
            created_count=created, merged_count=merged, category_count=len(pkg_to_local),
        )

    def _resolve_categories(self, pkg_cats: dict[str, dict]) -> dict[str, UUID]:
        local_cats = self._videos.list_categories()
        local_by_key = {(c.name, c.parent_id): c for c in local_cats}
        pkg_to_local: dict[str, UUID] = {}
        remaining = dict(pkg_cats)
        while remaining:
            progressed = False
            for pid, c in list(remaining.items()):
                parent_pid = c.get("parent_id")
                if parent_pid not in pkg_cats:
                    parent_pid = None
                if parent_pid is not None and parent_pid not in pkg_to_local:
                    continue
                local_parent_id = pkg_to_local.get(parent_pid) if parent_pid else None
                key = (c["name"], local_parent_id)
                existing_cat = local_by_key.get(key)
                if existing_cat is not None:
                    pkg_to_local[pid] = existing_cat.id
                else:
                    new_cat = Category.create(c["name"], parent_id=local_parent_id)
                    self._videos.save_category(new_cat)
                    local_by_key[key] = new_cat
                    pkg_to_local[pid] = new_cat.id
                del remaining[pid]
                progressed = True
            if not progressed:
                break   # 순환 참조 등 방어 — 정상 패키지에서는 도달하지 않는다
        return pkg_to_local

    def _create_video(self, v: dict, category_id: UUID | None, archive_path: str) -> VideoAggregate:
        channel = (
            ChannelInfo(v.get("channel_name", ""), v.get("channel_url", ""), v.get("channel_id", ""))
            if v.get("channel_name") else None
        )
        agg = VideoAggregate.create(
            url=VideoUrl(v["url"]), title=v.get("title") or v["url"], channel=channel,
            duration=Duration(int(v["duration_sec"])) if v.get("duration_sec") else None,
            published_at=datetime.fromisoformat(v["published_at"]) if v.get("published_at") else None,
            view_count=v.get("view_count"), category_id=category_id,
        )
        if v.get("notes"):
            agg.update_metadata(notes=v["notes"])
        if v.get("description"):
            agg.update_metadata(description=v["description"])
        tag_ids = [self._videos.get_or_create_tag(name).id for name in v.get("tags", [])]
        agg.set_tags(tag_ids)
        thumb_rel = v.get("thumbnail_rel")
        if thumb_rel:
            imported_rel = self._reader.import_thumbnail(archive_path, thumb_rel, agg.id)
            if imported_rel:
                agg.update_metadata(thumbnail_path=imported_rel)
        self._videos.save(agg)
        self._bus.publish_all(agg.pull_events())
        self._apply_song(agg.id, v.get("song"))
        return agg

    def _merge_video(
        self, existing: VideoAggregate, v: dict, local_cat_id: UUID | None,
        resolutions: dict[str, str], archive_path: str,
    ) -> None:
        def choose(field: str, existing_val, incoming_val):
            return incoming_val if resolutions.get(field) == "incoming" else existing_val

        title = choose("title", existing.video.title, v.get("title") or existing.video.title)
        notes = choose("notes", existing.video.notes, v.get("notes", "") or existing.video.notes)
        description = choose(
            "description", existing.video.description,
            v.get("description", "") or existing.video.description,
        )
        existing.update_metadata(title=title or None, notes=notes, description=description)

        if resolutions.get("category") == "incoming" and local_cat_id is not None:
            existing.assign_category(local_cat_id)
        elif existing.category_id is None and local_cat_id is not None:
            existing.assign_category(local_cat_id)

        incoming_tag_ids = [self._videos.get_or_create_tag(name).id for name in v.get("tags", [])]
        existing.set_tags(list(dict.fromkeys([*existing.tag_ids, *incoming_tag_ids])))

        thumb_rel = v.get("thumbnail_rel")
        if not existing.video.thumbnail_path and thumb_rel:
            imported_rel = self._reader.import_thumbnail(archive_path, thumb_rel, existing.id)
            if imported_rel:
                existing.update_metadata(thumbnail_path=imported_rel)

        self._videos.save(existing)
        self._bus.publish_all(existing.pull_events())
        self._merge_song(existing.id, v.get("song"), resolutions)

    def _apply_song(self, video_id: UUID, incoming: dict | None) -> None:
        if not incoming:
            return
        agg = SongInfoAggregate.create(video_id, is_song=bool(incoming.get("is_song")))
        for key in _SONG_TEXT_FIELDS:
            val = incoming.get(key, "")
            if val:
                agg.edit_field(key, val)
        lines = _lines_from_dicts(incoming.get("lyrics_lines") or [])
        if lines:
            agg.apply_fetched(
                lyrics_lines=lines,
                source=SongSourceRef(name=incoming.get("source_name") or "가져오기",
                                      url=incoming.get("source_url") or ""),
                force_lyrics=True,
            )
        offset = incoming.get("lyrics_offset_ms") or 0
        if offset:
            agg.set_lyrics_offset(int(offset))
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())

    def _merge_song(self, video_id: UUID, incoming: dict | None, resolutions: dict[str, str]) -> None:
        if not incoming:
            return
        agg = self._songs.get(video_id) or SongInfoAggregate.create(
            video_id, is_song=bool(incoming.get("is_song"))
        )

        def choose(key: str, existing_val, incoming_val):
            return incoming_val if resolutions.get(key) == "incoming" else existing_val

        for key in _SONG_TEXT_FIELDS:
            incoming_val = incoming.get(key) or ""
            existing_val = getattr(agg.info, key)
            if not incoming_val:
                continue
            chosen = choose(key, existing_val, incoming_val) if existing_val else incoming_val
            if chosen and chosen != existing_val:
                agg.edit_field(key, chosen)

        incoming_lines_raw = incoming.get("lyrics_lines") or []
        if incoming_lines_raw:
            want_incoming = resolutions.get("lyrics") == "incoming" or not agg.info.lyrics_lines
            if want_incoming:
                agg.apply_fetched(
                    lyrics_lines=_lines_from_dicts(incoming_lines_raw),
                    source=SongSourceRef(name=incoming.get("source_name") or "가져오기",
                                          url=incoming.get("source_url") or ""),
                    force_lyrics=True,
                )

        incoming_offset = incoming.get("lyrics_offset_ms") or 0
        if incoming_offset:
            if resolutions.get("lyrics_offset_ms") == "incoming" or agg.info.lyrics_offset_ms == 0:
                agg.set_lyrics_offset(int(incoming_offset))

        if incoming.get("is_song") and not agg.info.is_song:
            agg.set_song_flag(True)

        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())


def _lines_from_dicts(raw: list[dict]) -> list[LyricsLine]:
    return [
        LyricsLine(ln.get("original", ""), ln.get("translation", ""), ln.get("start_ms"))
        for ln in raw
    ]
