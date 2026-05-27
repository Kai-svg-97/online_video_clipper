# Video Description Bug Fix + Category Metadata Refresh + Category Sorting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix missing video description on registration, add category-level batch metadata refresh with tag cleanup, and sort categories alphabetically.

**Architecture:** Bug fix patches `AddVideoHandler`; category sort is a one-line SQL change; batch refresh adds a new command handler + QThread worker + progress dialog wired via signals. All changes follow the existing DDD layering (domain → application → infrastructure → GUI) and the MVVM pattern already in place.

**Tech Stack:** Python 3.10+, PyQt6, SQLite (sqlite3), yt-dlp via `YtDlpAdapter`

---

## Files Modified / Created

| Action | File |
|--------|------|
| Modify | `application/library/commands.py` |
| Modify | `domain/library/repositories.py` |
| Modify | `infrastructure/persistence/sqlite_video_repository.py` |
| Modify | `gui/view_models/library_vm.py` |
| Modify | `gui/panels/library_panel.py` |
| Modify | `main.py` |
| Modify | `tests/unit/domain/test_library.py` |
| Modify | `tests/integration/test_sqlite_video_repository.py` |

---

## Task 1: Fix Video Description Bug in AddVideoHandler

**Files:**
- Modify: `application/library/commands.py:67-157`

The handler already reads `desc = info.get("description") or ""` on line 100 to extract hashtags, but never stores it. Fix: capture it in a `description` variable and pass it to the aggregate.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/domain/test_library.py — add to TestVideoAggregate class

def test_update_metadata_description(self):
    agg = self._make()
    agg.pull_events()
    agg.update_metadata(description="hello world")
    assert agg.video.description == "hello world"
    events = agg.pull_events()
    assert any("description" in e.changed_fields for e in events)
```

Run: `pytest tests/unit/domain/test_library.py::TestVideoAggregate::test_update_metadata_description -v`
Expected: PASS (aggregate already supports description — this confirms the domain layer is ready)

- [ ] **Step 2: Modify `AddVideoHandler.handle()` to capture and save description**

In `application/library/commands.py`, make these changes:

**2a.** After line 74 (`thumbnail_url: str = ""`), add:
```python
        description: str = ""
```

**2b.** After line 100 (`desc = info.get("description") or ""`), add:
```python
                description = desc
```

**2c.** In the EXISTING video upsert path (lines 119–125), add `description=description or None`:
```python
            existing.update_metadata(
                title=title if title != cmd.url else None,
                description=description or None,
                channel=channel,
                duration=duration,
                published_at=published_at,
                view_count=view_count,
            )
```

**2d.** In the NEW video path (after line 148 `agg = VideoAggregate.create(...)`), add before `agg.set_tags(tag_ids)`:
```python
        if description:
            agg.update_metadata(description=description)
```

The full modified `handle()` signature block (lines 67–157 for reference):
```python
    def handle(self, cmd: AddVideoCommand) -> VideoAggregate:
        title: str = cmd.url
        channel: ChannelInfo | None = None
        duration: Duration | None = None
        published_at: datetime | None = None
        view_count: int | None = None
        meta_tags: list[str] = []
        thumbnail_url: str = ""
        description: str = ""          # NEW

        if cmd.fetch_metadata and self._ytdlp:
            try:
                info = self._ytdlp.fetch_metadata(cmd.url)
                title = info.get("title") or cmd.url
                if info.get("uploader"):
                    channel = ChannelInfo(
                        name=info.get("uploader", ""),
                        url=info.get("uploader_url") or "",
                        channel_id=info.get("channel_id") or info.get("uploader_id") or "",
                    )
                if info.get("duration"):
                    duration = Duration(int(info["duration"]))
                if info.get("upload_date"):
                    raw = info["upload_date"]
                    published_at = datetime(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
                view_count = info.get("view_count")
                thumbnail_url = info.get("thumbnail") or ""
                raw_tags: list[str] = list(info.get("tags") or [])
                raw_tags += list(info.get("categories") or [])
                desc = info.get("description") or ""
                description = desc                            # NEW
                desc_tags = re.findall(r"#([\w가-힣]{2,})", desc)
                raw_tags += desc_tags[:10]
                meta_tags = list(dict.fromkeys(
                    t.strip() for t in raw_tags if isinstance(t, str) and t.strip()
                ))
            except Exception:
                pass

        all_tag_names = list(dict.fromkeys([*cmd.tags, *meta_tags]))
        tag_ids: list[UUID] = []
        for tag_name in all_tag_names:
            tag = self._repo.get_or_create_tag(tag_name)
            tag_ids.append(tag.id)

        existing = self._repo.get_by_url(cmd.url)
        if existing is not None:
            existing.update_metadata(
                title=title if title != cmd.url else None,
                description=description or None,              # NEW
                channel=channel,
                duration=duration,
                published_at=published_at,
                view_count=view_count,
            )
            if tag_ids:
                existing.set_tags(tag_ids)
            if thumbnail_url and self._ytdlp and not existing.video.thumbnail_path:
                thumb_path = self._ytdlp.download_thumbnail(existing.id, thumbnail_url)
                if thumb_path:
                    existing.update_metadata(thumbnail_path=thumb_path)
            self._repo.save(existing)
            self._bus.publish_all(existing.pull_events())
            return existing

        url = VideoUrl(cmd.url)
        agg = VideoAggregate.create(
            url=url,
            title=title,
            channel=channel,
            duration=duration,
            published_at=published_at,
            view_count=view_count,
            favorite=cmd.favorite,
            category_id=cmd.category_id,
        )
        if description:                                        # NEW
            agg.update_metadata(description=description)      # NEW
        agg.set_tags(tag_ids)

        if thumbnail_url and self._ytdlp:
            thumb_path = self._ytdlp.download_thumbnail(agg.id, thumbnail_url)
            if thumb_path:
                agg.update_metadata(thumbnail_path=thumb_path)

        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add application/library/commands.py tests/unit/domain/test_library.py
git commit -m "fix: save video description from yt-dlp metadata on registration"
```

---

## Task 2: Sort Categories by Name in Repository

**Files:**
- Modify: `infrastructure/persistence/sqlite_video_repository.py:190-200`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_sqlite_video_repository.py — add new test class

class TestCategoryOrdering:
    def test_list_categories_sorted_by_name(self, repo):
        """Categories must come back in alphabetical order regardless of insert order."""
        from domain.library.entities import Category
        repo.save_category(Category.create("Zebra"))
        repo.save_category(Category.create("Apple"))
        repo.save_category(Category.create("Mango"))
        cats = repo.list_categories()
        names = [c.name for c in cats]
        assert names == sorted(names)
```

Run: `pytest tests/integration/test_sqlite_video_repository.py::TestCategoryOrdering -v`
Expected: FAIL (no ORDER BY yet)

- [ ] **Step 2: Add ORDER BY to `list_categories()`**

In `infrastructure/persistence/sqlite_video_repository.py`, change line 192:

```python
    def list_categories(self) -> list[Category]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT id, name, parent_id FROM categories ORDER BY name"
            ).fetchall()
        return [
            Category(
                id=UUID(r["id"]),
                name=r["name"],
                parent_id=UUID(r["parent_id"]) if r["parent_id"] else None,
            )
            for r in rows
        ]
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/integration/test_sqlite_video_repository.py::TestCategoryOrdering -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add infrastructure/persistence/sqlite_video_repository.py tests/integration/test_sqlite_video_repository.py
git commit -m "feat: sort categories by name in repository query"
```

---

## Task 3: Add `delete_zero_count_tags()` to Repository

**Files:**
- Modify: `domain/library/repositories.py:55-69`
- Modify: `infrastructure/persistence/sqlite_video_repository.py:249-264`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_sqlite_video_repository.py — add to existing file

class TestDeleteZeroCountTags:
    def test_deletes_tags_with_no_videos(self, repo):
        tag_a = repo.get_or_create_tag("used-tag")
        tag_b = repo.get_or_create_tag("orphan-tag")
        # Associate tag_a with a video
        from domain.library.value_objects import VideoUrl
        from domain.library.aggregates import VideoAggregate
        agg = VideoAggregate.create(VideoUrl("https://youtu.be/zzz111"), "Test")
        agg.set_tags([tag_a.id])
        repo.save(agg)
        # orphan-tag has no videos
        deleted = repo.delete_zero_count_tags()
        assert deleted == 1
        remaining = [t.name for t in repo.list_tags()]
        assert "used-tag" in remaining
        assert "orphan-tag" not in remaining
```

Run: `pytest tests/integration/test_sqlite_video_repository.py::TestDeleteZeroCountTags -v`
Expected: FAIL (method doesn't exist yet)

- [ ] **Step 2: Add abstract method to `IVideoRepository`**

In `domain/library/repositories.py`, add after `delete_tag`:

```python
    @abstractmethod
    def delete_zero_count_tags(self) -> int:
        """Delete tags not linked to any video. Returns count of deleted tags."""
        ...
```

- [ ] **Step 3: Implement in `SqliteVideoRepository`**

In `infrastructure/persistence/sqlite_video_repository.py`, add after `get_or_create_tag`:

```python
    def delete_zero_count_tags(self) -> int:
        with self._db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags)"
            )
            return cursor.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_sqlite_video_repository.py::TestDeleteZeroCountTags -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add domain/library/repositories.py infrastructure/persistence/sqlite_video_repository.py tests/integration/test_sqlite_video_repository.py
git commit -m "feat: add delete_zero_count_tags to video repository"
```

---

## Task 4: Add RefreshCategoryMetadataCommand and Handler

**Files:**
- Modify: `application/library/commands.py` (append at end)

This handler iterates all videos in the given categories (50 at a time), re-fetches full metadata from yt-dlp (including forced thumbnail re-download), saves, then deletes zero-count tags.

- [ ] **Step 1: Add command and handler to `application/library/commands.py`**

Append after the `ImportPlaylistHandler` class:

```python
@dataclass
class RefreshCategoryMetadataCommand:
    category_ids: list[UUID]  # empty list = refresh all videos


class RefreshCategoryMetadataHandler:
    """Re-fetches full metadata (title, description, tags, view count, thumbnail)
    for every video in the specified categories. Pass empty category_ids to
    refresh all videos in the library.
    """

    CHUNK_SIZE = 50

    def __init__(
        self,
        repo: IVideoRepository,
        event_bus: EventBus,
        ytdlp: YtDlpAdapter,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._ytdlp = ytdlp

    def handle(
        self,
        cmd: RefreshCategoryMetadataCommand,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> int:
        from domain.library.repositories import SearchQuery

        total = self._repo.count(SearchQuery(category_ids=cmd.category_ids))
        refreshed = 0
        offset = 0

        while True:
            batch = self._repo.search(SearchQuery(
                category_ids=cmd.category_ids,
                limit=self.CHUNK_SIZE,
                offset=offset,
            ))
            if not batch:
                break

            for agg in batch:
                try:
                    info = self._ytdlp.fetch_metadata(str(agg.video.url))
                    title = info.get("title") or agg.video.title
                    desc = info.get("description") or ""
                    channel = None
                    if info.get("uploader"):
                        channel = ChannelInfo(
                            name=info.get("uploader", ""),
                            url=info.get("uploader_url") or "",
                            channel_id=info.get("channel_id") or info.get("uploader_id") or "",
                        )
                    duration = Duration(int(info["duration"])) if info.get("duration") else None
                    published_at = None
                    if info.get("upload_date"):
                        raw = info["upload_date"]
                        published_at = datetime(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
                    view_count = info.get("view_count")
                    thumbnail_url = info.get("thumbnail") or ""

                    raw_tags: list[str] = list(info.get("tags") or [])
                    raw_tags += list(info.get("categories") or [])
                    desc_tags = re.findall(r"#([\w가-힣]{2,})", desc)
                    raw_tags += desc_tags[:10]
                    tag_names = list(dict.fromkeys(
                        t.strip() for t in raw_tags if isinstance(t, str) and t.strip()
                    ))

                    full_agg = self._repo.get_by_id(agg.id)
                    if full_agg is None:
                        continue

                    tag_ids = [self._repo.get_or_create_tag(t).id for t in tag_names]
                    full_agg.update_metadata(
                        title=title,
                        description=desc or None,
                        channel=channel,
                        duration=duration,
                        published_at=published_at,
                        view_count=view_count,
                    )
                    full_agg.set_tags(tag_ids)

                    if thumbnail_url:
                        thumb_path = self._ytdlp.download_thumbnail(full_agg.id, thumbnail_url)
                        if thumb_path:
                            full_agg.update_metadata(thumbnail_path=thumb_path)

                    self._repo.save(full_agg)
                    self._bus.publish_all(full_agg.pull_events())
                    refreshed += 1
                except Exception:
                    pass

            if on_progress:
                on_progress(min(offset + len(batch), total), total)
            offset += self.CHUNK_SIZE
            if len(batch) < self.CHUNK_SIZE:
                break

        self._repo.delete_zero_count_tags()
        return refreshed
```

- [ ] **Step 2: Run lint check**

Run: `ruff check application/library/commands.py`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 3: Commit**

```bash
git add application/library/commands.py
git commit -m "feat: add RefreshCategoryMetadataCommand and handler"
```

---

## Task 5: Update LibraryViewModel with Refresh Support

**Files:**
- Modify: `gui/view_models/library_vm.py`

Add a `_RefreshMetadataWorker` QThread, new signals, and a `refresh_category_metadata()` method. The handler is injected (same pattern as other handlers).

- [ ] **Step 1: Add imports at top of `library_vm.py`**

In the existing import block (lines 7–28), add to the `application.library.commands` import:

```python
from application.library.commands import (
    AddVideoCommand,
    AddVideoHandler,
    AssignCategoryCommand,
    AssignCategoryHandler,
    CreateCategoryCommand,
    CreateCategoryHandler,
    DeleteCategoryCommand,
    DeleteCategoryHandler,
    DeleteTagCommand,
    DeleteTagHandler,
    DeleteVideoCommand,
    DeleteVideoHandler,
    MarkWatchedCommand,
    MarkWatchedHandler,
    MoveCategoryCommand,
    MoveCategoryHandler,
    RefreshCategoryMetadataCommand,    # NEW
    RefreshCategoryMetadataHandler,    # NEW
    RenameCategoryCommand,
    RenameCategoryHandler,
    UpdateVideoCommand,
    UpdateVideoHandler,
)
```

- [ ] **Step 2: Add `_RefreshMetadataWorker` class after `_AddVideoWorker`**

After the `_AddVideoWorker` class (around line 62), add:

```python
class _RefreshMetadataWorker(QThread):
    progress = pyqtSignal(int, int)   # current, total
    finished_ok = pyqtSignal(int)     # count of refreshed videos
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: RefreshCategoryMetadataHandler,
        cmd: RefreshCategoryMetadataCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            count = self._handler.handle(
                self._cmd,
                on_progress=lambda cur, total: self.progress.emit(cur, total),
            )
            self.finished_ok.emit(count)
        except Exception as exc:
            self.finished_err.emit(str(exc))
```

- [ ] **Step 3: Add signals and parameter to `LibraryViewModel`**

**3a.** In `LibraryViewModel` class body, add two new signals after `video_add_finished`:

```python
    metadata_refresh_progress = pyqtSignal(int, int)  # current, total
    metadata_refresh_finished = pyqtSignal(int)        # count refreshed
```

**3b.** In `LibraryViewModel.__init__()`, add parameter `refresh_metadata: RefreshCategoryMetadataHandler` and store it:

```python
    def __init__(
        self,
        get_videos: GetVideosHandler,
        search_videos: SearchVideosHandler,
        get_categories: GetCategoriesHandler,
        get_tags: GetTagsHandler,
        add_video: AddVideoHandler,
        update_video: UpdateVideoHandler,
        delete_video: DeleteVideoHandler,
        mark_watched: MarkWatchedHandler,
        create_category: CreateCategoryHandler,
        rename_category: RenameCategoryHandler,
        delete_category: DeleteCategoryHandler,
        move_category: MoveCategoryHandler,
        delete_tag: DeleteTagHandler,
        assign_category: AssignCategoryHandler,
        get_video_detail: GetVideoDetailHandler,
        refresh_metadata: RefreshCategoryMetadataHandler,   # NEW
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        # ... existing assignments ...
        self._refresh_metadata = refresh_metadata           # NEW
        self._refresh_metadata_workers: list[_RefreshMetadataWorker] = []  # NEW
```

- [ ] **Step 4: Add `refresh_category_metadata()` method and `_on_refresh_ok()` helper**

Append before `_on_add_ok` at the end of `LibraryViewModel`:

```python
    def refresh_category_metadata(self, category_id: UUID | None) -> None:
        category_ids = (
            self._resolve_category_ids(category_id)
            if category_id is not None
            else []
        )
        cmd = RefreshCategoryMetadataCommand(category_ids=category_ids)
        worker = _RefreshMetadataWorker(self._refresh_metadata, cmd, self)
        worker.progress.connect(self.metadata_refresh_progress)
        worker.finished_ok.connect(self._on_refresh_metadata_ok)
        worker.finished_err.connect(lambda err: self.error_occurred.emit(err))
        worker.finished.connect(lambda: self._refresh_metadata_workers.remove(worker))
        self._refresh_metadata_workers.append(worker)
        worker.start()

    def _on_refresh_metadata_ok(self, count: int) -> None:
        self._refresh_videos()
        self._refresh_tags()
        self.metadata_refresh_finished.emit(count)
```

- [ ] **Step 5: Run unit tests to verify no import/syntax errors**

Run: `pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add gui/view_models/library_vm.py
git commit -m "feat: add metadata refresh support to LibraryViewModel"
```

---

## Task 6: Update `_CategoryTree` and `LibraryPanel` for Refresh UI

**Files:**
- Modify: `gui/panels/library_panel.py`

Add a `refresh_metadata_req` signal to `_CategoryTree`, wire the popup menu, and add a progress dialog handler in `LibraryPanel`.

- [ ] **Step 1: Add `QProgressDialog` to imports in `library_panel.py`**

In the `QWidgets` import block (lines 28–55), add `QProgressDialog`:

```python
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,       # NEW
    QPushButton,
    QScrollArea,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
```

- [ ] **Step 2: Add `refresh_metadata_req` signal to `_CategoryTree`**

In `_CategoryTree` class body (around lines 837–844), add the new signal:

```python
class _CategoryTree(QTreeWidget):
    url_dropped          = pyqtSignal(str, object)
    video_moved          = pyqtSignal(object, object)
    category_reparented  = pyqtSignal(object, object)
    add_category_req     = pyqtSignal(object)
    rename_category_req  = pyqtSignal(object, str)
    delete_category_req  = pyqtSignal(object, str)
    refresh_metadata_req = pyqtSignal(object)   # NEW — cat_id UUID or None (=all)
```

- [ ] **Step 3: Add "메타데이터 일괄 갱신" menu item to `_show_context_menu()`**

In `_show_context_menu()` (lines 870–899), add the refresh option. It should appear for both the "전체 영상" item (`cat_id is None`) and for specific categories:

Replace the current method with:

```python
    def _show_context_menu(self, pos: QPoint) -> None:
        self._edit_timer.stop()
        self._pending_edit_cat_id = None

        item = self.itemAt(pos)
        cat_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = QMenu(self)

        add_act = QAction("카테고리 추가", self)
        add_act.triggered.connect(lambda: self.add_category_req.emit(None))
        menu.addAction(add_act)

        if cat_id is not None:
            name = item.text(0)
            sub_act = QAction("하위 카테고리 추가", self)
            sub_act.triggered.connect(lambda: self.add_category_req.emit(cat_id))
            menu.addAction(sub_act)
            menu.addSeparator()
            ren_act = QAction("이름 변경 (F2)", self)
            ren_act.triggered.connect(lambda checked=False, cid=cat_id: self._start_edit_by_cat_id(cid))
            menu.addAction(ren_act)
            del_act = QAction("삭제", self)
            del_act.triggered.connect(lambda: self.delete_category_req.emit(cat_id, name))
            menu.addAction(del_act)

        if item is not None:
            menu.addSeparator()
            ref_act = QAction("메타데이터 일괄 갱신", self)
            ref_act.triggered.connect(
                lambda checked=False, cid=cat_id: self.refresh_metadata_req.emit(cid)
            )
            menu.addAction(ref_act)

        menu.exec(self.viewport().mapToGlobal(pos))
```

- [ ] **Step 4: Add progress dialog state and signal connections in `LibraryPanel`**

**4a.** In `LibraryPanel.__init__()`, after creating the ViewModel attribute, add:

```python
        self._refresh_dlg: QProgressDialog | None = None
```

**4b.** In `LibraryPanel._connect_signals()` (around line 1441), add:

```python
        self._cat_tree.refresh_metadata_req.connect(self._on_refresh_metadata)
        self._vm.metadata_refresh_progress.connect(self._on_refresh_progress)
        self._vm.metadata_refresh_finished.connect(self._on_refresh_finished)
```

**4c.** Add the three handler methods to `LibraryPanel`:

```python
    def _on_refresh_metadata(self, category_id) -> None:
        if self._refresh_dlg is not None:
            return  # already running
        self._refresh_dlg = QProgressDialog(
            "메타데이터 갱신 중...", None, 0, 100, self
        )
        self._refresh_dlg.setWindowTitle("메타데이터 일괄 갱신")
        self._refresh_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._refresh_dlg.setMinimumDuration(0)
        self._refresh_dlg.setValue(0)
        self._refresh_dlg.show()
        self._vm.refresh_category_metadata(category_id)

    def _on_refresh_progress(self, current: int, total: int) -> None:
        if self._refresh_dlg is not None and total > 0:
            self._refresh_dlg.setValue(int(current / total * 100))

    def _on_refresh_finished(self, count: int) -> None:
        if self._refresh_dlg is not None:
            self._refresh_dlg.close()
            self._refresh_dlg = None
```

- [ ] **Step 5: Run lint check**

Run: `ruff check gui/panels/library_panel.py gui/view_models/library_vm.py`
Expected: No new errors

- [ ] **Step 6: Commit**

```bash
git add gui/panels/library_panel.py gui/view_models/library_vm.py
git commit -m "feat: add metadata batch refresh menu and progress dialog to library panel"
```

---

## Task 7: Wire RefreshCategoryMetadataHandler in main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add import and handler creation**

**1a.** In `main.py` import block (lines 17–28), add `RefreshCategoryMetadataHandler`:

```python
from application.library.commands import (
    AddVideoHandler,
    AssignCategoryHandler,
    CreateCategoryHandler,
    DeleteCategoryHandler,
    DeleteTagHandler,
    DeleteVideoHandler,
    MarkWatchedHandler,
    MoveCategoryHandler,
    RefreshCategoryMetadataHandler,    # NEW
    RenameCategoryHandler,
    UpdateVideoHandler,
)
```

**1b.** In `main()` after line 87 (`delete_tag_h = DeleteTagHandler(...)`), add:

```python
    refresh_metadata = RefreshCategoryMetadataHandler(video_repo, event_bus, ytdlp)
```

**1c.** In the `LibraryViewModel(...)` call (lines 115–131), add the new keyword argument:

```python
    library_vm = LibraryViewModel(
        get_videos=get_videos,
        search_videos=search_videos,
        get_categories=get_cats,
        get_tags=get_tags,
        add_video=add_video,
        update_video=update_video,
        delete_video=delete_video,
        mark_watched=mark_watched,
        create_category=create_category,
        rename_category=rename_category,
        delete_category=delete_category,
        move_category=move_category,
        delete_tag=delete_tag_h,
        assign_category=assign_category,
        get_video_detail=get_video_detail,
        refresh_metadata=refresh_metadata,    # NEW
    )
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: wire RefreshCategoryMetadataHandler into main app"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Bug: description saved on registration — Task 1
- ✅ Feature: batch metadata refresh in category popup — Tasks 3, 4, 5, 6, 7
- ✅ Feature: tag counter refresh + zero-count deletion after refresh — Task 3 (repo method), Task 4 (handler calls it), Task 5 (`_on_refresh_metadata_ok` calls `_refresh_tags()`)
- ✅ Feature: categories sorted by name — Task 2

**Type consistency check:**
- `RefreshCategoryMetadataCommand.category_ids: list[UUID]` — used consistently in Tasks 4, 5
- `LibraryViewModel.refresh_category_metadata(category_id: UUID | None)` — resolves to `list[UUID]` before passing to command
- `_RefreshMetadataWorker` takes `RefreshCategoryMetadataHandler` (not the command) + command separately — matches constructor in Task 5
- `on_progress: Callable[[int, int], None] | None` — lambda in worker matches `pyqtSignal(int, int)` in Task 5
- `metadata_refresh_finished` emits `int` (count) — matches `_on_refresh_finished(count: int)` in Task 6

**No placeholders:** All steps contain complete code.
