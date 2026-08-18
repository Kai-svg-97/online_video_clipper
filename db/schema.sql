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
    gemini_summary  TEXT    NOT NULL DEFAULT '',
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

-- Gemini 요약 실패 사유 (상세 화면 안내 문구용, 진단 정보라 로컬 전용).
-- videos 행을 늘리지 않도록 video_descriptions 와 같은 방식으로 분리한다.
-- status: "no_button"(YouTube가 그 영상에 요약 기능 미제공) | "not_signed_in" | "error"
-- 요약을 성공적으로 가져오면 해당 행을 삭제한다.
CREATE TABLE IF NOT EXISTS video_summary_status (
    video_id   TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
    gemini_summary  TEXT NOT NULL DEFAULT '',
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

-- =========================================================
-- Song context (노래 정보 — 가수·앨범·제목·가사, Video와 1:1)
-- =========================================================

CREATE TABLE IF NOT EXISTS song_info (
    video_id        TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    is_song         INTEGER NOT NULL DEFAULT 0,
    artist          TEXT NOT NULL DEFAULT '',
    album           TEXT NOT NULL DEFAULT '',
    song_title      TEXT NOT NULL DEFAULT '',
    release_year    TEXT NOT NULL DEFAULT '',
    lyrics_json     TEXT NOT NULL DEFAULT '[]',   -- [{"o": 원문, "t": 한글번역, "s": 시작ms}, ...]
    lyrics_language TEXT NOT NULL DEFAULT '',      -- ISO 639-1 ("" 미상)
    lyrics_offset_ms INTEGER NOT NULL DEFAULT 0,   -- 자막 싱크 보정(ms). 양수 = 자막 지연
    source_name     TEXT NOT NULL DEFAULT '',      -- 가사 출처 표시 이름
    source_url      TEXT NOT NULL DEFAULT '',
    manual_fields   TEXT NOT NULL DEFAULT '[]',    -- 사용자가 직접 편집한 필드명(JSON array)
    updated_at      TEXT NOT NULL
);

-- 가사·메타데이터 출처(사이트) 관리형 레지스트리 — 조회 체인 순서/사용여부 제어
CREATE TABLE IF NOT EXISTS lyrics_sources (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    provider_key TEXT NOT NULL,          -- lrclib | genius | melon | bugs | genie | ...
    base_url     TEXT NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1,
    priority     INTEGER NOT NULL DEFAULT 100   -- 작을수록 먼저 시도
);

-- 앨범 정보 캐시 (외부 조회 결과) — 파생 데이터라 동기화 대상이 아니다.
-- 앨범은 저장 단위가 아니라 노래 정보(가수·앨범)에서 파생되는 묶음이므로, 여기에는
-- '다시 조회하지 않기 위한' 자켓·발매일·수록곡 목록만 담는다. 지우면 다시 받아온다.
CREATE TABLE IF NOT EXISTS album_cache (
    album_key    TEXT PRIMARY KEY,              -- domain.song.album.make_album_key
    album_title  TEXT NOT NULL DEFAULT '',
    artist       TEXT NOT NULL DEFAULT '',
    artwork_url  TEXT NOT NULL DEFAULT '',
    artwork_path TEXT NOT NULL DEFAULT '',      -- THUMBNAIL_DIR 기준 상대경로 ('' = 미다운로드)
    description  TEXT NOT NULL DEFAULT '',
    release_date TEXT NOT NULL DEFAULT '',
    genre        TEXT NOT NULL DEFAULT '',
    copyright    TEXT NOT NULL DEFAULT '',
    track_count  INTEGER NOT NULL DEFAULT 0,
    tracks_json  TEXT NOT NULL DEFAULT '[]',    -- [{"n": 번호, "t": 제목, "a": 가수, "d": 초}, ...]
    source_name  TEXT NOT NULL DEFAULT '',
    source_url   TEXT NOT NULL DEFAULT '',
    fetched_at   TEXT NOT NULL
);

-- 라이브러리에 없는 수록곡에 자동으로 붙인 스트리밍 영상(official 음원 추정).
-- 라이브러리에 있는 곡은 조회 시점에 제목 매칭으로 찾으므로 저장하지 않는다 —
-- 여기 남는 건 '내가 등록하지 않은' 자동 매핑뿐이라, 목록의 출처 배지가 이 표의
-- 존재 여부와 정확히 일치한다.
CREATE TABLE IF NOT EXISTS album_track_links (
    album_key     TEXT NOT NULL,
    -- 트랙 번호는 디스크 안에서만 유일하다(2장짜리 앨범은 disc2가 다시 1번부터).
    disc_no       INTEGER NOT NULL DEFAULT 1,
    track_no      INTEGER NOT NULL,
    track_title   TEXT NOT NULL DEFAULT '',
    stream_url    TEXT NOT NULL DEFAULT '',
    stream_title  TEXT NOT NULL DEFAULT '',
    stream_channel TEXT NOT NULL DEFAULT '',
    stream_yt_id  TEXT NOT NULL DEFAULT '',
    duration_sec  INTEGER,
    origin        TEXT NOT NULL DEFAULT 'auto',  -- auto = 자동 검색으로 붙임
    created_at    TEXT NOT NULL,
    PRIMARY KEY (album_key, disc_no, track_no)
);

-- 앨범 미상 노래의 외부 조회 상태 — 실패한 곡을 화면 열 때마다 다시 조회하지 않기 위한 기록.
-- 성공하면 song_info.album이 채워져 자연히 제 앨범으로 옮겨 가므로 found=1 행은 흔적일 뿐이다.
CREATE TABLE IF NOT EXISTS album_lookup_state (
    video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    found    INTEGER NOT NULL DEFAULT 0,
    tried_at TEXT NOT NULL
);

-- =========================================================
-- Sync context (클라우드 동기화 — 레코드 단위 oplog CRDT)
-- 아래 테이블은 로컬 전용(동기화 대상 아님) — 병합 레지스터 상태를 materialize한다.
-- 컴팩션 시 op 로그로부터 재생성 가능하다.
-- =========================================================

-- 자연키 ↔ 로컬 UUID 매핑 + 존재(presence) 레지스터.
-- present=0 이면 tombstone. pres_lamport/pres_install 로 존재 LWW를 판정한다.
CREATE TABLE IF NOT EXISTS sync_identity (
    entity       TEXT NOT NULL,
    nkey         TEXT NOT NULL,
    local_uuid   TEXT NOT NULL,
    present      INTEGER NOT NULL DEFAULT 1,
    pres_lamport INTEGER NOT NULL DEFAULT 0,
    pres_install TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (entity, nkey)
);

-- 필드/참조 값 레지스터 — 필드별 승자 clock(lamport, install)을 기록해 필드 단위 LWW를 판정한다.
CREATE TABLE IF NOT EXISTS sync_field_clock (
    entity  TEXT NOT NULL,
    nkey    TEXT NOT NULL,
    field   TEXT NOT NULL,
    lamport INTEGER NOT NULL,
    install TEXT NOT NULL,
    PRIMARY KEY (entity, nkey, field)
);

-- 이미 적용한 op_id — 멱등 재적용 방지.
CREATE TABLE IF NOT EXISTS sync_applied_ops (
    op_id      TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
