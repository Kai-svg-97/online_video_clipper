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
CREATE INDEX IF NOT EXISTS idx_videos_category   ON videos(category_id);
CREATE INDEX IF NOT EXISTS idx_videos_favorite   ON videos(favorite);
CREATE INDEX IF NOT EXISTS idx_videos_watched    ON videos(watched);
CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_tags_tag    ON video_tags(tag_id);

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
