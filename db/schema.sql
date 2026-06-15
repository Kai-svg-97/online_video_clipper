-- YouTube Content Manager — SQLite Schema
-- WAL mode is enabled at connection time, not here.

PRAGMA foreign_keys = ON;

-- =========================================================
-- Library context
-- =========================================================

CREATE TABLE IF NOT EXISTS categories (
    id          TEXT PRIMARY KEY,           -- UUID as text
    name        TEXT NOT NULL,
    parent_id   TEXT REFERENCES categories(id) ON DELETE SET NULL,
    UNIQUE (name, parent_id)
);

CREATE TABLE IF NOT EXISTS tags (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS videos (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    channel_name    TEXT,
    channel_url     TEXT,
    channel_id      TEXT,
    duration_sec    INTEGER,
    published_at    TEXT,                   -- ISO-8601
    view_count      INTEGER,
    favorite        INTEGER NOT NULL DEFAULT 0,
    watched         INTEGER NOT NULL DEFAULT 0,
    notes           TEXT    NOT NULL DEFAULT '',
    thumbnail_path  TEXT    NOT NULL DEFAULT '',
    category_id     TEXT    REFERENCES categories(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
    -- description is stored separately in video_descriptions for lazy loading
);

CREATE TABLE IF NOT EXISTS video_descriptions (
    video_id    TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS video_tags (
    video_id    TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    tag_id      TEXT NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
    PRIMARY KEY (video_id, tag_id)
);

-- Full-text search index on title, notes (description loaded separately)
CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
    title,
    notes,
    content=videos,
    content_rowid=rowid
);

-- Keep FTS in sync
CREATE TRIGGER IF NOT EXISTS videos_ai AFTER INSERT ON videos BEGIN
    INSERT INTO videos_fts(rowid, title, notes) VALUES (new.rowid, new.title, new.notes);
END;
CREATE TRIGGER IF NOT EXISTS videos_ad AFTER DELETE ON videos BEGIN
    INSERT INTO videos_fts(videos_fts, rowid, title, notes)
        VALUES ('delete', old.rowid, old.title, old.notes);
END;
CREATE TRIGGER IF NOT EXISTS videos_au AFTER UPDATE ON videos BEGIN
    INSERT INTO videos_fts(videos_fts, rowid, title, notes)
        VALUES ('delete', old.rowid, old.title, old.notes);
    INSERT INTO videos_fts(rowid, title, notes) VALUES (new.rowid, new.title, new.notes);
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_videos_category    ON videos(category_id);
CREATE INDEX IF NOT EXISTS idx_videos_favorite    ON videos(favorite);
CREATE INDEX IF NOT EXISTS idx_videos_watched     ON videos(watched);
CREATE INDEX IF NOT EXISTS idx_videos_created_at  ON videos(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_tags_tag     ON video_tags(tag_id);
-- 정렬 가속 인덱스 (published_at·title·view_count·duration_sec ORDER BY 플랜에서 풀스캔 방지)
CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_title        ON videos(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_videos_view_count   ON videos(view_count DESC);
CREATE INDEX IF NOT EXISTS idx_videos_duration_sec ON videos(duration_sec);

-- =========================================================
-- Download context
-- =========================================================

CREATE TABLE IF NOT EXISTS download_history (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL,
    quality         TEXT NOT NULL,
    format          TEXT NOT NULL,
    subtitle_langs  TEXT NOT NULL DEFAULT '[]',  -- JSON array
    include_thumbnail   INTEGER NOT NULL DEFAULT 1,
    include_metadata    INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL,               -- completed | failed | cancelled
    file_path       TEXT NOT NULL DEFAULT '',
    file_size_bytes INTEGER,
    error_msg       TEXT NOT NULL DEFAULT '',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dl_history_created ON download_history(created_at DESC);

-- =========================================================
-- Clip context
-- =========================================================

CREATE TABLE IF NOT EXISTS clips (
    id              TEXT PRIMARY KEY,
    source_video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    file_path       TEXT NOT NULL DEFAULT '',
    thumbnail_path  TEXT NOT NULL DEFAULT '',
    start_sec       REAL NOT NULL,
    end_sec         REAL NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clips_video ON clips(source_video_id);

-- =========================================================
-- Monitoring context
-- =========================================================

-- =========================================================
-- Playlist context (YouTube 재생목록 + 로컬 재생목록)
-- =========================================================

CREATE TABLE IF NOT EXISTS playlists (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    yt_playlist_id  TEXT,                  -- NULL = 로컬 전용; "PLxxxxxxx" = YouTube 연동
    source          TEXT NOT NULL DEFAULT 'local',  -- 'local' | 'youtube'
    item_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_playlists_yt_id
    ON playlists(yt_playlist_id)
    WHERE yt_playlist_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id  TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    video_id     TEXT NOT NULL REFERENCES videos(id)    ON DELETE CASCADE,
    position     INTEGER NOT NULL DEFAULT 0,
    added_at     TEXT NOT NULL,
    PRIMARY KEY (playlist_id, video_id)
);

CREATE INDEX IF NOT EXISTS idx_playlist_items_order
    ON playlist_items(playlist_id, position);

-- 재생목록 폴더 (앱 내 조직 구조 — YouTube에는 미반영)
CREATE TABLE IF NOT EXISTS playlist_folders (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'local',  -- 'local' | 'youtube'
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- YouTube OAuth2 토큰 저장 (Phase 2용 — 지금은 테이블만 생성)
CREATE TABLE IF NOT EXISTS yt_oauth_tokens (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- =========================================================
-- Monitoring context
-- =========================================================

-- 카테고리 내 영상 수동 순서 (없으면 기본 정렬 적용)
CREATE TABLE IF NOT EXISTS category_video_order (
    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    video_id    TEXT NOT NULL REFERENCES videos(id)    ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    PRIMARY KEY (category_id, video_id)
);
CREATE INDEX IF NOT EXISTS idx_cat_video_order ON category_video_order(category_id, position);

-- =========================================================
-- Monitoring context
-- =========================================================

CREATE TABLE IF NOT EXISTS channel_subscriptions (
    id              TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL UNIQUE,
    channel_name    TEXT NOT NULL,
    channel_url     TEXT NOT NULL,
    keywords        TEXT NOT NULL DEFAULT '[]',  -- JSON array
    min_duration_sec    INTEGER,
    max_duration_sec    INTEGER,
    auto_download   INTEGER NOT NULL DEFAULT 0,
    dl_quality      TEXT NOT NULL DEFAULT 'best',
    dl_format       TEXT NOT NULL DEFAULT 'mp4',
    is_active       INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    created_at      TEXT NOT NULL
);
