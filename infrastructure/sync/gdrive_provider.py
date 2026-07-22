"""Google Drive 클라우드 provider (ICloudSyncProvider 구현).

인증: google-auth-oauthlib InstalledAppFlow(run_local_server) — `oauth_adapter` 패턴 재사용.
스코프는 **`drive.file`**(이 앱이 만든 파일만) 로 최소화한다. 토큰은 ISecretStore(keyring,
부재 시 파일)에 JSON 으로 둔다 — DB 밖이라 시작 pull(pre-DB)에서도 접근 가능.

Drive 는 경로가 아니라 **파일 ID 모델**이라, 우리 remote_path("oplog/...", "media/...")를
앱 루트 폴더 아래 폴더 트리로 에뮬레이션한다(경로→id 캐시). 파일 전송은 requests 로 직접
호출한다(youtube_api_adapter 와 동일한 이유: TLS 인터셉트 환경 견고성 + 테스트 용이).
resumable 업로드 세션(청크 PUT)으로 진행률·중단복구를 지원한다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from application.sync.ports import ProgressCb, RemoteFile
from infrastructure.sync.rest_client import RestClient

logger = logging.getLogger(__name__)

_API = "https://www.googleapis.com/drive/v3"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_TOKEN_KEY = "gdrive.token"
_CHUNK = 8 * 1024 * 1024  # 8MB (256KiB 배수 — Drive resumable 청크 요건)


def _esc(name: str) -> str:
    """Drive q 파라미터의 문자열 리터럴 이스케이프."""
    return name.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveProvider:
    """ICloudSyncProvider 를 구조적으로 만족."""

    def __init__(
        self,
        secret_store,
        root_name: str = "OnlineVideoClipperSync",
        *,
        rest: RestClient | None = None,
    ) -> None:
        self._secret = secret_store
        self._root = root_name.strip("/")
        self._creds = None
        self._folder_ids: dict[str, str] = {}  # rel_dir("" = 앱 루트) → folder id
        self._rest = rest or RestClient(self._bearer, self._force_refresh)

    # -- 신원 -----------------------------------------------------------
    def provider_key(self) -> str:
        return "gdrive"

    def is_authenticated(self) -> bool:
        try:
            return bool(self._bearer())
        except Exception:
            return False

    def account_name(self) -> str | None:
        try:
            r = self._rest.request("GET", f"{_API}/about", params={"fields": "user"})
            if r.status_code == 200:
                return (r.json().get("user") or {}).get("emailAddress")
        except Exception:
            logger.exception("Google Drive 계정명 조회 실패")
        return None

    def ensure_root(self) -> None:
        self._app_root_id()

    # -- google 자격증명 ------------------------------------------------
    def _load_creds(self):
        if self._creds is not None:
            return self._creds
        import json  # noqa: PLC0415

        from google.oauth2.credentials import Credentials  # noqa: PLC0415

        raw = self._secret.get(_TOKEN_KEY) if self._secret else None
        if not raw:
            return None
        data = json.loads(raw)
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes", _SCOPES),
        )
        expiry = data.get("expiry")
        if expiry:
            from datetime import datetime  # noqa: PLC0415

            creds.expiry = datetime.fromisoformat(expiry)
        self._creds = creds
        return creds

    def _save_creds(self, creds) -> None:
        import json  # noqa: PLC0415

        data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else _SCOPES,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }
        if self._secret:
            self._secret.set(_TOKEN_KEY, json.dumps(data))
        self._creds = creds

    def _refresh(self, creds) -> None:
        import requests as _rq  # noqa: PLC0415
        import urllib3  # noqa: PLC0415

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from google.auth.transport.requests import Request as _GReq  # noqa: PLC0415

        s = _rq.Session()
        s.verify = False
        creds.refresh(_GReq(session=s))
        self._save_creds(creds)

    def _bearer(self) -> str:
        creds = self._load_creds()
        if creds is None:
            raise RuntimeError("Google Drive 인증 필요 — 먼저 연결하세요")
        if not creds.valid and creds.refresh_token:
            self._refresh(creds)
        return creds.token

    def _force_refresh(self) -> None:
        creds = self._load_creds()
        if creds is not None and creds.refresh_token:
            self._refresh(creds)

    def connect_run_flow(self, client_id: str, client_secret: str) -> bool:
        """브라우저 OAuth 플로우를 실행하고 토큰을 저장한다(연결 UI에서 호출)."""
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, _SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        self._save_creds(creds)
        return True

    def disconnect(self) -> None:
        self._creds = None
        self._folder_ids.clear()
        if self._secret:
            self._secret.delete(_TOKEN_KEY)

    # -- 폴더 트리(경로→id) --------------------------------------------
    def _query_files(self, q: str, fields: str) -> list[dict]:
        """q 조건에 맞는 파일을 페이지네이션하며 모두 모은다."""
        out: list[dict] = []
        page_token = None
        while True:
            params = {
                "q": q,
                "fields": f"nextPageToken,files({fields})",
                "spaces": "drive",
                "pageSize": 200,
            }
            if page_token:
                params["pageToken"] = page_token
            r = self._rest.request("GET", f"{_API}/files", params=params)
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    def _create_folder(self, parent_id: str, name: str) -> str:
        body = {"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}
        r = self._rest.request("POST", f"{_API}/files", json=body, params={"fields": "id"})
        r.raise_for_status()
        return r.json()["id"]

    def _find_child_folder(self, parent_id: str, name: str) -> str | None:
        q = (
            f"'{parent_id}' in parents and name='{_esc(name)}' "
            f"and mimeType='{_FOLDER_MIME}' and trashed=false"
        )
        files = self._query_files(q, "id")
        return files[0]["id"] if files else None

    def _app_root_id(self) -> str:
        if "" in self._folder_ids:
            return self._folder_ids[""]
        q = (
            f"'root' in parents and name='{_esc(self._root)}' "
            f"and mimeType='{_FOLDER_MIME}' and trashed=false"
        )
        files = self._query_files(q, "id")
        fid = files[0]["id"] if files else self._create_folder("root", self._root)
        self._folder_ids[""] = fid
        return fid

    def _folder_id(self, rel_dir: str, create: bool) -> str | None:
        rel_dir = rel_dir.strip("/")
        if rel_dir in self._folder_ids:
            return self._folder_ids[rel_dir]
        parent_id = self._app_root_id()
        built = ""
        for seg in (rel_dir.split("/") if rel_dir else []):
            built = f"{built}/{seg}" if built else seg
            if built in self._folder_ids:
                parent_id = self._folder_ids[built]
                continue
            fid = self._find_child_folder(parent_id, seg)
            if fid is None:
                if not create:
                    return None
                fid = self._create_folder(parent_id, seg)
            self._folder_ids[built] = fid
            parent_id = fid
        return parent_id

    def _find_file(self, remote_path: str) -> dict | None:
        rp = remote_path.strip("/")
        parts = rp.split("/")
        parent_dir = "/".join(parts[:-1])
        name = parts[-1]
        parent_id = self._folder_id(parent_dir, create=False)
        if parent_id is None:
            return None
        q = (
            f"'{parent_id}' in parents and name='{_esc(name)}' "
            f"and mimeType!='{_FOLDER_MIME}' and trashed=false"
        )
        files = self._query_files(q, "id,name,size,md5Checksum,modifiedTime")
        return files[0] if files else None

    @staticmethod
    def _to_remote_file(rel_path: str, item: dict) -> RemoteFile:
        return RemoteFile(
            path=rel_path,
            size=int(item.get("size", 0)),
            modified=item.get("modifiedTime", ""),
            remote_id=item.get("id", ""),
            checksum=item.get("md5Checksum", ""),
        )

    # -- 목록/조회 ------------------------------------------------------
    def list_files(self, prefix: str = "") -> list[RemoteFile]:
        out: list[RemoteFile] = []
        self._walk(self._app_root_id(), "", out)
        return [rf for rf in out if rf.path.startswith(prefix)]

    def _walk(self, folder_id: str, rel: str, out: list[RemoteFile]) -> None:
        q = f"'{folder_id}' in parents and trashed=false"
        children = self._query_files(q, "id,name,size,md5Checksum,modifiedTime,mimeType")
        for c in children:
            name = c.get("name", "")
            crel = f"{rel}/{name}" if rel else name
            if c.get("mimeType") == _FOLDER_MIME:
                self._walk(c["id"], crel, out)
            else:
                out.append(self._to_remote_file(crel, c))

    def stat(self, remote_path: str) -> RemoteFile | None:
        item = self._find_file(remote_path)
        return self._to_remote_file(remote_path.strip("/"), item) if item else None

    # -- 업로드 ---------------------------------------------------------
    def upload_file(
        self, local_path: Path, remote_path: str, on_progress: ProgressCb | None = None
    ) -> RemoteFile:
        local_path = Path(local_path)
        size = local_path.stat().st_size
        with open(local_path, "rb") as f:
            item = self._upload_stream(remote_path, f, size, on_progress)
        return self._to_remote_file(remote_path.strip("/"), item)

    def _upload_stream(self, remote_path: str, fileobj, size: int, on_progress) -> dict:
        rp = remote_path.strip("/")
        parts = rp.split("/")
        parent_dir = "/".join(parts[:-1])
        name = parts[-1]
        parent_id = self._folder_id(parent_dir, create=True)
        existing = self._find_file(remote_path)

        if existing:
            init = self._rest.request(
                "PATCH",
                f"{_UPLOAD}/{existing['id']}",
                params={"uploadType": "resumable"},
                json={"name": name},
                headers={"Content-Type": "application/json; charset=UTF-8"},
            )
        else:
            init = self._rest.request(
                "POST",
                _UPLOAD,
                params={"uploadType": "resumable"},
                json={"name": name, "parents": [parent_id]},
                headers={"Content-Type": "application/json; charset=UTF-8"},
            )
        init.raise_for_status()
        session_uri = init.headers["Location"]
        sess = self._rest._sess()  # noqa: SLF001 — 세션 URI 는 자체 인증 포함, raw PUT
        last: dict = {}

        if size == 0:
            resp = sess.put(
                session_uri,
                data=b"",
                headers={"Content-Range": "bytes */0"},
                allow_redirects=False,
                timeout=120,
            )
            resp.raise_for_status()
            if on_progress:
                on_progress(0, 0)
            return resp.json() if resp.content else {}

        sent = 0
        while sent < size:
            chunk = fileobj.read(_CHUNK)
            if not chunk:
                break
            end = sent + len(chunk) - 1
            resp = sess.put(
                session_uri,
                data=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{end}/{size}",
                },
                allow_redirects=False,  # 308(Resume Incomplete)을 따라가지 않도록
                timeout=120,
            )
            if resp.status_code == 308:
                pass  # 청크 수신됨, 계속
            else:
                resp.raise_for_status()
                if resp.content:
                    last = resp.json()
            sent += len(chunk)
            if on_progress:
                on_progress(sent, size)
        return last

    # -- 다운로드/삭제/텍스트 -------------------------------------------
    def download_file(
        self, remote_path: str, local_path: Path, on_progress: ProgressCb | None = None
    ) -> None:
        item = self._find_file(remote_path)
        if item is None:
            raise FileNotFoundError(remote_path)
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        r = self._rest.request(
            "GET", f"{_API}/files/{item['id']}", params={"alt": "media"}, stream=True
        )
        r.raise_for_status()
        total = int(item.get("size", 0)) or int(r.headers.get("Content-Length", 0))
        done = 0
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=_CHUNK):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total or done)

    def delete_file(self, remote_path: str) -> None:
        item = self._find_file(remote_path)
        if item is None:
            return
        r = self._rest.request("DELETE", f"{_API}/files/{item['id']}")
        if r.status_code not in (204, 200, 404):
            r.raise_for_status()

    def read_text(self, remote_path: str) -> str | None:
        item = self._find_file(remote_path)
        if item is None:
            return None
        r = self._rest.request(
            "GET", f"{_API}/files/{item['id']}", params={"alt": "media"}
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    def write_text(self, remote_path: str, content: str) -> None:
        import io  # noqa: PLC0415

        data = content.encode("utf-8")
        self._upload_stream(remote_path, io.BytesIO(data), len(data), None)
