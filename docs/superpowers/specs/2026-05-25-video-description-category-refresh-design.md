# Design: Video Description Bug Fix + Category Metadata Refresh + Category Sorting

**Date:** 2026-05-25  
**Status:** Approved

---

## 1. Bug Fix — Video Description Not Saved on Registration

**Problem:** `AddVideoHandler.handle()` fetches yt-dlp metadata but never extracts the `description` field. The `Video` entity, `video_descriptions` DB table, and `VideoAggregate.update_metadata()` all support description — the gap is only in the command handler.

**Changes:**
- `application/library/commands.py` — extract `info.get("description", "")` in `AddVideoHandler.handle()` and pass to `VideoAggregate.create()`
- If `UpdateVideoCommand` lacks a `description` field, add it so the field can also be updated later

---

## 2. Feature — Category Popup: Batch Metadata Refresh

**User flow:** Right-click a category in the tree → "메타데이터 일괄 갱신" → progress dialog appears → all videos in that category are refreshed → tag counts recalculated → zero-count tags deleted.

**Processing:** Videos are fetched 50 at a time (existing pagination). Each video is re-fetched from yt-dlp for full metadata: title, description, tags, view count, thumbnail. Runs in a `QThread` to keep the UI responsive.

**New components:**

| Location | Change |
|---|---|
| `application/library/commands.py` | `RefreshCategoryMetadataCommand` + handler |
| `domain/library/repositories.py` | `delete_zero_count_tags()` on `IVideoRepository` |
| `infrastructure/persistence/sqlite_video_repository.py` | Implement `delete_zero_count_tags()` |
| `gui/panels/library_panel.py` | Popup menu item + `QProgressDialog` + worker `QThread` |
| `gui/view_models/library_vm.py` | `refresh_category_metadata(category_id)` method |

**Tag cleanup:** After all videos in the category are processed, execute:
```sql
DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags);
```
Then call `_refresh_tags()` to update the ViewModel.

---

## 3. Feature — Categories Sorted by Name

**Change:** One SQL edit in `infrastructure/persistence/sqlite_video_repository.py`:

```python
# list_categories()
rows = conn.execute(
    "SELECT id, name, parent_id FROM categories ORDER BY name"
).fetchall()
```

This ensures categories are always returned in alphabetical order at the repository level, so all callers automatically see sorted results.
