"""OneDrive(Microsoft Graph) 클라우드 provider (ICloudSyncProvider 구현).

인증: msal.PublicClientApplication + SerializableTokenCache(ISecretStore에 직렬화).
파일 CRUD: Graph v1.0 경로 주소지정(`/me/drive/root:/<path>`)을 requests 로 직접 호출한다
(youtube_api_adapter 의 requests+verify=False+401 재시도 패턴을 rest_client 로 공유).

Graph 는 경로 기반이라 우리 remote_path("oplog/...", "media/...")를 앱 루트 폴더 아래에
그대로 매핑한다. msal 은 지연 import 라 이 모듈은 msal 없이도 import 된다(테스트 시
rest 를 주입해 우회).
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from application.sync.ports import ProgressCb, RemoteFile
from infrastructure.sync.rest_client import RestClient

logger = logging.getLogger(__name__)

_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["Files.ReadWrite", "offline_access"]
_AUTHORITY = "https://login.microsoftonline.com/consumers"
_CHUNK = 3276800  # 320 KiB * 10 — Graph 업로드 세션 청크는 320KiB 배수여야 함
_SIMPLE_MAX = 4 * 1024 * 1024  # 4MB 이하는 단순 PUT


class OneDriveProvider:
    """ICloudSyncProvider 를 구조적으로 만족."""

    def __init__(
        self,
        secret_store,
        client_id: str | None = None,
        root_name: str = "OnlineVideoClipperSync",
        *,
        rest: RestClient | None = None,
    ) -> None:
        self._secret = secret_store
        self._client_id = client_id or (secret_store.get("onedrive.client_id") if secret_store else None)
        self._root = root_name.strip("/")
        self._cache_key = "onedrive.tokens"
        self._token: str | None = None
        self._rest = rest or RestClient(self._bearer, self._force_refresh)

    # -- 신원 -----------------------------------------------------------
    def provider_key(self) -> str:
        return "onedrive"

    def is_authenticated(self) -> bool:
        try:
            return self._acquire_silent() is not None
        except Exception:
            logger.exception("OneDrive 인증 확인 실패")
            return False

    def account_name(self) -> str | None:
        try:
            r = self._rest.request("GET", f"{_BASE}/me")
            if r.status_code == 200:
                d = r.json()
                return d.get("userPrincipalName") or d.get("displayName")
        except Exception:
            logger.exception("OneDrive 계정명 조회 실패")
        return None

    def ensure_root(self) -> None:
        self._ensure_folder("")

    # -- msal 토큰 ------------------------------------------------------
    def _msal_app(self):
        import msal  # noqa: PLC0415

        cache = msal.SerializableTokenCache()
        blob = self._secret.get(self._cache_key) if self._secret else None
        if blob:
            cache.deserialize(blob)
        app = msal.PublicClientApplication(
            self._client_id, authority=_AUTHORITY, token_cache=cache
        )
        return app, cache

    def _save_cache(self, cache) -> None:
        if cache.has_state_changed and self._secret:
            self._secret.set(self._cache_key, cache.serialize())

    def _acquire_silent(self) -> str | None:
        if not self._client_id:
            return None
        app, cache = self._msal_app()
        accounts = app.get_accounts()
        if not accounts:
            return None
        result = app.acquire_token_silent(_SCOPES, account=accounts[0])
        self._save_cache(cache)
        token = result.get("access_token") if result else None
        if token:
            self._token = token
        return token

    def _bearer(self) -> str:
        if self._token:
            return self._token
        token = self._acquire_silent()
        if not token:
            raise RuntimeError("OneDrive 인증 필요 — 먼저 연결하세요")
        return token

    def _force_refresh(self) -> None:
        self._token = None
        self._acquire_silent()

    def connect_interactive(self) -> bool:
        """브라우저로 대화형 인증을 수행하고 토큰 캐시를 저장한다(연결 UI에서 호출)."""
        app, cache = self._msal_app()
        result = app.acquire_token_interactive(_SCOPES)
        self._save_cache(cache)
        token = result.get("access_token") if result else None
        if token:
            self._token = token
            return True
        return False

    def disconnect(self) -> None:
        self._token = None
        if self._secret:
            self._secret.delete(self._cache_key)

    # -- 경로 헬퍼 ------------------------------------------------------
    def _item_path(self, remote_path: str) -> str:
        """remote_path 를 앱 루트 하위 절대 아이템 경로로 만든다."""
        rp = remote_path.strip("/")
        return f"{self._root}/{rp}" if rp else self._root

    @staticmethod
    def _enc(item_path: str) -> str:
        """경로 세그먼트별 URL 인코딩(구분자 / 는 보존)."""
        return "/".join(quote(seg, safe="") for seg in item_path.split("/"))

    def _item_url(self, remote_path: str, suffix: str = "") -> str:
        # suffix 는 경로 종결자 ':' 를 포함한다(예: ":/content", ":/children").
        enc = self._enc(self._item_path(remote_path))
        return f"{_BASE}/me/drive/root:/{enc}{suffix}"

    @staticmethod
    def _to_remote_file(rel_path: str, item: dict) -> RemoteFile:
        checksum = ""
        file_facet = item.get("file") or {}
        hashes = file_facet.get("hashes") or {}
        checksum = hashes.get("quickXorHash", "") or hashes.get("sha256Hash", "")
        return RemoteFile(
            path=rel_path,
            size=int(item.get("size", 0)),
            modified=item.get("lastModifiedDateTime", ""),
            remote_id=item.get("id", ""),
            checksum=checksum,
        )

    # -- 폴더 생성 ------------------------------------------------------
    def _ensure_folder(self, rel_dir: str) -> None:
        """앱 루트부터 rel_dir 까지 폴더 체인을 멱등 생성한다."""
        # 앱 루트 먼저: 드라이브 root 의 children 으로 생성.
        segments = [self._root] + [s for s in rel_dir.strip("/").split("/") if s]
        parent_url = f"{_BASE}/me/drive/root"  # 드라이브 최상위
        built = ""
        for seg in segments:
            self._create_child_folder(parent_url, seg)
            built = f"{built}/{seg}" if built else seg
            parent_url = f"{_BASE}/me/drive/root:/{self._enc(built)}:"

    def _create_child_folder(self, parent_url: str, name: str) -> None:
        body = {
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",  # 이미 있으면 409 → 무시
        }
        r = self._rest.request("POST", f"{parent_url}/children", json=body)
        if r.status_code in (200, 201) or r.status_code == 409:
            return
        logger.warning("OneDrive 폴더 생성 응답 %s: %s", r.status_code, name)

    # -- 목록/조회 ------------------------------------------------------
    def list_files(self, prefix: str = "") -> list[RemoteFile]:
        out: list[RemoteFile] = []
        self._walk("", out)
        return [rf for rf in out if rf.path.startswith(prefix)]

    def _walk(self, rel: str, out: list[RemoteFile]) -> None:
        url = self._item_url(rel, ":/children") if rel else (
            f"{_BASE}/me/drive/root:/{self._enc(self._root)}:/children"
        )
        while url:
            r = self._rest.request("GET", url)
            if r.status_code == 404:
                return
            r.raise_for_status()
            data = r.json()
            for item in data.get("value", []):
                name = item.get("name", "")
                child_rel = f"{rel}/{name}" if rel else name
                if "folder" in item:
                    self._walk(child_rel, out)
                else:
                    out.append(self._to_remote_file(child_rel, item))
            url = data.get("@odata.nextLink")

    def stat(self, remote_path: str) -> RemoteFile | None:
        r = self._rest.request("GET", self._item_url(remote_path))
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return self._to_remote_file(remote_path.strip("/"), r.json())

    # -- 업로드 ---------------------------------------------------------
    def upload_file(
        self, local_path: Path, remote_path: str, on_progress: ProgressCb | None = None
    ) -> RemoteFile:
        local_path = Path(local_path)
        size = local_path.stat().st_size
        self._ensure_parent(remote_path)
        with open(local_path, "rb") as f:
            if size <= _SIMPLE_MAX:
                item = self._put_content(remote_path, f.read(), on_progress, size)
            else:
                item = self._upload_session(remote_path, f, size, on_progress)
        return self._to_remote_file(remote_path.strip("/"), item)

    def _ensure_parent(self, remote_path: str) -> None:
        parent = "/".join(remote_path.strip("/").split("/")[:-1])
        self._ensure_folder(parent)

    def _put_content(self, remote_path, data: bytes, on_progress, size) -> dict:
        r = self._rest.request(
            "PUT",
            self._item_url(remote_path, ":/content"),
            data=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        r.raise_for_status()
        if on_progress:
            on_progress(size, size)
        return r.json()

    def _upload_session(self, remote_path, fileobj, size, on_progress) -> dict:
        r = self._rest.request(
            "POST",
            self._item_url(remote_path, ":/createUploadSession"),
            json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
        )
        r.raise_for_status()
        upload_url = r.json()["uploadUrl"]
        sent = 0
        last: dict = {}
        # 세션 URL 은 자체 인증 토큰을 포함하므로 Bearer 없이 raw 세션으로 PUT 한다.
        sess = self._rest._sess()  # noqa: SLF001 — 의도적 재사용
        while sent < size:
            chunk = fileobj.read(_CHUNK)
            if not chunk:
                break
            end = sent + len(chunk) - 1
            resp = sess.put(
                upload_url,
                data=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{end}/{size}",
                },
                timeout=120,
            )
            resp.raise_for_status()
            sent += len(chunk)
            if on_progress:
                on_progress(sent, size)
            if resp.status_code in (200, 201):
                last = resp.json()
        return last

    # -- 다운로드/삭제/텍스트 -------------------------------------------
    def download_file(
        self, remote_path: str, local_path: Path, on_progress: ProgressCb | None = None
    ) -> None:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        r = self._rest.request("GET", self._item_url(remote_path, ":/content"), stream=True)
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=_CHUNK):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total or done)

    def delete_file(self, remote_path: str) -> None:
        r = self._rest.request("DELETE", self._item_url(remote_path))
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def read_text(self, remote_path: str) -> str | None:
        r = self._rest.request("GET", self._item_url(remote_path, ":/content"))
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    def write_text(self, remote_path: str, content: str) -> None:
        data = content.encode("utf-8")
        self._ensure_parent(remote_path)
        self._put_content(remote_path, data, None, len(data))
