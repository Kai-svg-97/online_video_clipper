"""YouTube Data API v3 어댑터 — 재생목록 CRUD + 아이템 관리.

httplib2/googleapiclient 없이 requests로 직접 REST 호출한다.
VPN·보안 소프트웨어가 HTTPS를 인터셉트하는 환경(SSL WRONG_VERSION_NUMBER 등)에서
httplib2는 TLS 핸드셰이크 자체가 실패하므로, requests + verify=False 로 대체한다.
"""
from __future__ import annotations

import re

_BASE = "https://www.googleapis.com/youtube/v3"


def _extract_yt_video_id(url) -> str:
    """YouTube URL에서 영상 ID를 추출한다. VideoUrl 값 객체도 허용한다."""
    url = str(url) if url else ""
    if not url:
        return ""
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    m = re.search(r"/shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    return ""


class YouTubeApiAdapter:
    """YouTube Data API v3 래퍼.

    credentials: google.oauth2.credentials.Credentials
    """

    def __init__(self, credentials) -> None:
        self._creds = credentials
        self._session = None

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
        """액세스 토큰이 유효한지 확인하고, 만료됐으면 갱신한다."""
        if not self._creds.valid:
            from google.auth.transport.requests import Request as _GReq
            self._creds.refresh(_GReq(session=self._get_session()))

    def _hdrs(self) -> dict:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._creds.token}"}

    def _force_refresh(self):
        """액세스 토큰을 강제로 갱신한다 (401 재시도용)."""
        from google.auth.transport.requests import Request as _GReq  # noqa: PLC0415
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
            pass
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
            return None
