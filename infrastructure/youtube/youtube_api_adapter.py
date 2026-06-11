"""YouTube Data API v3 어댑터 — 재생목록 CRUD + 아이템 관리.

httplib2/googleapiclient 없이 requests로 직접 REST 호출한다.
VPN·보안 소프트웨어가 HTTPS를 인터셉트하는 환경(SSL WRONG_VERSION_NUMBER 등)에서
httplib2는 TLS 핸드셰이크 자체가 실패하므로, requests + verify=False 로 대체한다.
"""
from __future__ import annotations

import logging
import re

from domain.library.value_objects import extract_youtube_video_id

logger = logging.getLogger(__name__)

_BASE = "https://www.googleapis.com/youtube/v3"

# 파싱 로직은 도메인으로 이동했다. 기존 참조 호환을 위한 얇은 별칭.
_extract_yt_video_id = extract_youtube_video_id

# ISO 8601 기간(예: "PT1H2M3S", "PT45S")
_ISO8601_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def _to_int(value) -> int | None:
    """YouTube API statistics의 문자열 카운트를 정수로 변환 (실패 시 None)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso8601_duration(value) -> int | None:
    """contentDetails.duration(ISO 8601)을 초 단위 정수로 변환 (실패 시 None)."""
    if not value or not isinstance(value, str):
        return None
    m = _ISO8601_DURATION_RE.match(value)
    if not m:
        return None
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    total = h * 3600 + mi * 60 + s
    return total or None


class YouTubeApiAdapter:
    """YouTube Data API v3 래퍼.

    credentials: google.oauth2.credentials.Credentials
    """

    def __init__(self, credentials) -> None:
        import threading  # noqa: PLC0415
        self._creds = credentials
        self._session = None
        # get_latest_upload_dates의 ThreadPoolExecutor가 공유 세션·자격증명을 동시 사용하므로
        # 토큰 갱신(creds.refresh)은 스레드 안전하지 않다 → 락으로 직렬화한다.
        self._token_lock = threading.Lock()

    # ── HTTP 헬퍼 ────────────────────────────────────────────────────────────

    def _get_session(self):
        if self._session is None:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            s = requests.Session()
            s.verify = False
            self._session = s
        return self._session

    def _ensure_token(self):
        """액세스 토큰이 유효한지 확인하고, 만료됐으면 갱신한다(스레드 안전)."""
        with self._token_lock:
            if not self._creds.valid:
                from google.auth.transport.requests import Request as _GReq  # noqa: PLC0415
                self._creds.refresh(_GReq(session=self._get_session()))

    def _hdrs(self) -> dict:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._creds.token}"}

    def _force_refresh(self):
        """액세스 토큰을 강제로 갱신한다 (401 재시도용, 스레드 안전)."""
        from google.auth.transport.requests import Request as _GReq  # noqa: PLC0415
        with self._token_lock:
            self._creds.refresh(_GReq(session=self._get_session()))

    def _get(self, resource: str, params: dict) -> dict:
        r = self._get_session().get(
            f"{_BASE}/{resource}", headers=self._hdrs(), params=params, timeout=30
        )
        if r.status_code == 401:
            self._force_refresh()
            r = self._get_session().get(
                f"{_BASE}/{resource}", headers=self._hdrs(), params=params, timeout=30
            )
        r.raise_for_status()
        return r.json()

    def _post(self, resource: str, params: dict, body: dict) -> dict:
        r = self._get_session().post(
            f"{_BASE}/{resource}", headers=self._hdrs(), params=params, json=body, timeout=30
        )
        if r.status_code == 401:
            self._force_refresh()
            r = self._get_session().post(
                f"{_BASE}/{resource}", headers=self._hdrs(), params=params, json=body, timeout=30
            )
        r.raise_for_status()
        return r.json()

    def _put(self, resource: str, params: dict, body: dict) -> dict:
        r = self._get_session().put(
            f"{_BASE}/{resource}", headers=self._hdrs(), params=params, json=body, timeout=30
        )
        if r.status_code == 401:
            self._force_refresh()
            r = self._get_session().put(
                f"{_BASE}/{resource}", headers=self._hdrs(), params=params, json=body, timeout=30
            )
        r.raise_for_status()
        return r.json()

    def _delete(self, resource: str, params: dict) -> None:
        r = self._get_session().delete(
            f"{_BASE}/{resource}", headers=self._hdrs(), params=params, timeout=30
        )
        if r.status_code == 401:
            self._force_refresh()
            r = self._get_session().delete(
                f"{_BASE}/{resource}", headers=self._hdrs(), params=params, timeout=30
            )
        r.raise_for_status()

    # ── 재생목록 관리 ────────────────────────────────────────────────────────

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy_status: str = "private",
    ) -> str:
        """YouTube 재생목록 생성 → yt_playlist_id 반환."""
        resp = self._post(
            "playlists",
            {"part": "snippet,status"},
            {
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": privacy_status},
            },
        )
        return resp["id"]

    def delete_playlist(self, yt_playlist_id: str) -> None:
        """YouTube 재생목록 삭제."""
        self._delete("playlists", {"id": yt_playlist_id})

    def update_playlist_title(self, yt_playlist_id: str, new_title: str) -> None:
        """YouTube 재생목록 제목 변경."""
        self._put(
            "playlists",
            {"part": "snippet"},
            {"id": yt_playlist_id, "snippet": {"title": new_title}},
        )

    # ── 재생목록 아이템 관리 ──────────────────────────────────────────────────

    def add_video(self, yt_playlist_id: str, yt_video_id: str) -> str:
        """재생목록에 영상 추가 → yt_item_id 반환."""
        resp = self._post(
            "playlistItems",
            {"part": "snippet"},
            {
                "snippet": {
                    "playlistId": yt_playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": yt_video_id,
                    },
                }
            },
        )
        return resp["id"]

    def remove_video(self, yt_item_id: str) -> None:
        """재생목록 아이템 삭제 (yt_item_id = playlistItems.id)."""
        self._delete("playlistItems", {"id": yt_item_id})

    def update_item_position(
        self,
        yt_item_id: str,
        yt_playlist_id: str,
        yt_video_id: str,
        position: int,
    ) -> None:
        """재생목록 아이템 순서를 변경한다."""
        self._put(
            "playlistItems",
            {"part": "snippet"},
            {
                "id": yt_item_id,
                "snippet": {
                    "playlistId": yt_playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": yt_video_id,
                    },
                    "position": position,
                },
            },
        )

    # ── 구독 / 재생목록 읽기 ──────────────────────────────────────────────────

    def list_subscriptions(self) -> list[dict]:
        """내 YouTube 구독 채널 목록 반환.

        Returns: [{"id": channel_id, "name": channel_name, "url": channel_url}, ...]
        """
        result, page_token = [], None
        while True:
            params: dict = {"part": "snippet", "mine": "true", "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            resp = self._get("subscriptions", params)
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                ch_id = snippet.get("resourceId", {}).get("channelId", "")
                ch_name = snippet.get("title", "")
                result.append({
                    "id": ch_id,
                    "name": ch_name,
                    "url": f"https://www.youtube.com/channel/{ch_id}" if ch_id else "",
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return result

    def get_videos_channels(self, video_ids: list[str]) -> dict[str, dict]:
        """영상 ID 목록의 메타데이터를 videos.list로 일괄 조회.

        구독 피드/채널 영상의 yt-dlp 플랫 추출은 영상 ID·길이 정도만 주고
        채널·게시일·조회수를 주지 않으므로, 영상 ID로 역조회해 보강한다.
        한 번에 최대 50개씩 배치 호출한다.
        Returns: {video_id: {"channel_id", "channel_name", "published_at"(ISO),
                             "view_count", "duration_sec"}, ...}
        """
        result: dict[str, dict] = {}
        ids = [v for v in video_ids if v]
        for i in range(0, len(ids), 50):
            batch = ids[i:i + 50]
            try:
                resp = self._get(
                    "videos",
                    {"part": "snippet,statistics,contentDetails",
                     "id": ",".join(batch), "maxResults": 50},
                )
            except Exception:
                logger.exception("영상 메타데이터 일괄 조회 실패")
                continue
            for item in resp.get("items", []):
                vid = item.get("id", "")
                if not vid:
                    continue
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                content = item.get("contentDetails", {})
                result[vid] = {
                    "channel_id": snippet.get("channelId", ""),
                    "channel_name": snippet.get("channelTitle", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "view_count": _to_int(stats.get("viewCount")),
                    "duration_sec": _parse_iso8601_duration(content.get("duration")),
                }
        return result

    def list_channels(self, channel_ids: list[str]) -> dict[str, dict]:
        """채널 ID 목록의 메타데이터를 channels.list로 일괄 조회.

        Returns: {channel_id: {"title", "thumbnail", "subscriber_count",
                               "video_count", "hidden_subscriber_count",
                               "uploads_playlist_id"}, ...}
        한 번에 최대 50개씩 배치 호출한다.
        """
        result: dict[str, dict] = {}
        ids = [c for c in channel_ids if c]
        for i in range(0, len(ids), 50):
            batch = ids[i:i + 50]
            try:
                resp = self._get(
                    "channels",
                    {"part": "snippet,statistics,contentDetails",
                     "id": ",".join(batch), "maxResults": 50},
                )
            except Exception:
                logger.exception("채널 메타데이터 일괄 조회 실패")
                continue
            for item in resp.get("items", []):
                cid = item.get("id", "")
                if not cid:
                    continue
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                content = item.get("contentDetails", {})
                thumbs = snippet.get("thumbnails", {})
                thumb = (
                    (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
                    or ""
                )
                hidden = bool(stats.get("hiddenSubscriberCount"))
                result[cid] = {
                    "title": snippet.get("title", ""),
                    "thumbnail": thumb,
                    "subscriber_count": (
                        None if hidden else _to_int(stats.get("subscriberCount"))
                    ),
                    "video_count": _to_int(stats.get("videoCount")),
                    "hidden_subscriber_count": hidden,
                    "uploads_playlist_id": (
                        content.get("relatedPlaylists", {}).get("uploads", "")
                    ),
                }
        return result

    def get_latest_upload_dates(
        self, uploads_by_channel: dict[str, str]
    ) -> dict[str, str]:
        """채널별 최신 업로드 영상의 게시 시각(ISO)을 반환한다.

        uploads_by_channel: {channel_id: uploads_playlist_id}
        Returns: {channel_id: published_at(ISO)} — 조회 실패/없음은 생략.

        업로드 재생목록의 첫 항목(=최신)만 가져온다(쿼터 1단위/채널).
        채널 수만큼 호출이므로 스레드풀로 병렬 조회한다.
        """
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

        pairs = [(c, p) for c, p in uploads_by_channel.items() if c and p]
        if not pairs:
            return {}
        # 병렬 호출 전에 토큰을 한 번 갱신해 401 경합을 줄인다.
        try:
            self._ensure_token()
        except Exception:
            logger.exception("토큰 갱신 실패 — 최신 업로드 조회 계속 진행")

        def _fetch(pair: tuple[str, str]) -> tuple[str, str]:
            cid, pl = pair
            try:
                resp = self._get(
                    "playlistItems",
                    {"part": "contentDetails", "playlistId": pl, "maxResults": 1},
                )
                items = resp.get("items", [])
                if items:
                    iso = items[0].get("contentDetails", {}).get("videoPublishedAt", "")
                    return cid, iso or ""
            except Exception as exc:
                # 업로드 재생목록이 비활성/빈 채널은 404가 정상적으로 발생한다.
                # 채널 단위로 무시되는 비치명적 실패이므로 조용히(debug) 남긴다.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 404:
                    logger.debug("채널 업로드 재생목록 없음(404): %s", cid)
                else:
                    logger.debug("채널 최신 업로드 시각 조회 실패: %s (%s)", cid, exc)
            return cid, ""

        out: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            for cid, iso in ex.map(_fetch, pairs):
                if iso:
                    out[cid] = iso
        return out

    def list_playlists(self) -> list[dict]:
        """내 YouTube 재생목록 목록 반환.

        Returns: [{"id": yt_playlist_id, "title": str, "count": int}, ...]
        """
        result, page_token = [], None
        while True:
            params: dict = {"part": "snippet,contentDetails", "mine": "true", "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            resp = self._get("playlists", params)
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                details = item.get("contentDetails", {})
                result.append({
                    "id": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "count": details.get("itemCount", 0),
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return result

    def get_channel_name(self) -> str | None:
        """현재 인증된 YouTube 채널명 반환."""
        try:
            resp = self._get("channels", {"part": "snippet", "mine": "true"})
            items = resp.get("items") or []
            if items:
                return items[0].get("snippet", {}).get("title")
        except Exception:
            logger.exception("YouTube 채널명 조회 실패")
        return None

    def list_items(self, yt_playlist_id: str) -> list[dict]:
        """재생목록 아이템 목록 반환.

        Returns: [{"yt_video_id": str, "yt_item_id": str, "position": int}, ...]
        """
        result, page_token = [], None
        while True:
            params: dict = {
                "part": "snippet",
                "playlistId": yt_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = self._get("playlistItems", params)
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                result.append({
                    "yt_video_id": snippet.get("resourceId", {}).get("videoId", ""),
                    "yt_item_id": item["id"],
                    "position": snippet.get("position", 0),
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return result

    def list_items_full(self, yt_playlist_id: str) -> list[dict]:
        """재생목록 아이템 + 영상 메타데이터 반환 (비공개 재생목록 포함).

        yt-dlp fallback용으로, fetch_playlist_videos()와 호환되는 dict 구조를 반환한다.
        Returns: [{"url", "title", "position", "yt_video_id", "yt_item_id",
                   "channel_name", "thumbnail_url", "upload_date", ...}, ...]
        """
        result, page_token = [], None
        while True:
            params: dict = {
                "part": "snippet,contentDetails",
                "playlistId": yt_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = self._get("playlistItems", params)
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                content = item.get("contentDetails", {})
                yt_vid_id = snippet.get("resourceId", {}).get("videoId", "")
                if not yt_vid_id:
                    continue
                thumbs = snippet.get("thumbnails", {})
                thumb_url = (
                    (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
                    or f"https://i.ytimg.com/vi/{yt_vid_id}/mqdefault.jpg"
                )
                pub_at = (content.get("videoPublishedAt") or "")[:10].replace("-", "")
                result.append({
                    "url": f"https://www.youtube.com/watch?v={yt_vid_id}",
                    "title": snippet.get("title", ""),
                    "position": snippet.get("position", 0),
                    "yt_video_id": yt_vid_id,
                    "yt_item_id": item["id"],
                    "channel_name": snippet.get("videoOwnerChannelTitle", ""),
                    "duration_sec": None,
                    "thumbnail_url": thumb_url,
                    "upload_date": pub_at,
                    "view_count": None,
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return result

    def get_playlist_title(self, yt_playlist_id: str) -> str | None:
        """재생목록 제목 반환. 존재하지 않거나 권한 없으면 None."""
        try:
            resp = self._get(
                "playlists",
                {"part": "snippet", "id": yt_playlist_id, "maxResults": 1},
            )
            items = resp.get("items") or []
            return items[0]["snippet"]["title"] if items else None
        except Exception:
            logger.exception("재생목록 제목 조회 실패")
            return None
