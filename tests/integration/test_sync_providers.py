"""provider 어댑터 테스트 (실계정 없이 in-memory fake HTTP 로 로직 검증).

실계정 왕복(OAuth+실전송)은 로컬에서만 가능하다. 여기서는 순수하게 검증 가능한 부분만
다룬다: RestClient 401 재시도, 경로·쿼리·URL 빌드, 폴더 트리 에뮬레이션, 페이지네이션,
텍스트/목록/삭제 왕복. 대용량 업로드 세션(청크 PUT)은 실전송 검증 대상이라 제외.
"""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

from infrastructure.sync.gdrive_provider import GoogleDriveProvider, _esc
from infrastructure.sync.onedrive_provider import OneDriveProvider
from infrastructure.sync.rest_client import RestClient


class FakeResp:
    def __init__(self, status=200, body=None, text=None, headers=None, content=None):
        self.status_code = status
        self._body = body
        self._text = text
        self.headers = headers or {}
        self._content = content

    def json(self):
        if self._body is None and self._text is not None:
            return json.loads(self._text)
        return self._body

    @property
    def text(self):
        if self._text is not None:
            return self._text
        return json.dumps(self._body) if self._body is not None else ""

    @property
    def content(self):
        if self._content is not None:
            return self._content
        return self.text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        data = self._content if self._content is not None else self.text.encode()
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]


# ---------------------------------------------------------------------------
# RestClient
# ---------------------------------------------------------------------------


class _RetrySession:
    """첫 요청은 401, 재시도는 200 을 돌려주는 세션."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, **kw):
        self.calls.append(headers.get("Authorization"))
        if len(self.calls) == 1:
            return FakeResp(401)
        return FakeResp(200, {"ok": True})


class TestRestClient:
    def test_401_triggers_force_refresh_and_retry(self):
        refreshed = {"n": 0}

        def token_provider():
            return token_provider.cur

        token_provider.cur = "old"

        def force_refresh():
            refreshed["n"] += 1
            token_provider.cur = "new"

        sess = _RetrySession()
        rc = RestClient(token_provider, force_refresh, session=sess)
        r = rc.request("GET", "https://x/y")
        assert r.status_code == 200
        assert refreshed["n"] == 1
        assert sess.calls == ["Bearer old", "Bearer new"]

    def test_no_refresh_when_not_provided(self):
        sess = _RetrySession()
        rc = RestClient(lambda: "tok", None, session=sess)
        r = rc.request("GET", "https://x/y")
        assert r.status_code == 401  # 재시도 없음
        assert len(sess.calls) == 1


# ---------------------------------------------------------------------------
# OneDrive — 경로/URL 빌드 + 경로기반 fake 왕복
# ---------------------------------------------------------------------------


class TestOneDrivePaths:
    def test_item_path_and_url(self):
        p = OneDriveProvider(secret_store=None, client_id="cid", root_name="App", rest=None)
        assert p._item_path("media/manifest.json") == "App/media/manifest.json"
        assert p._item_path("") == "App"
        url = p._item_url("oplog/inst A/000001.ndjson", ":/content")
        # 공백 등 특수문자는 세그먼트별로 인코딩, / 는 보존.
        assert url == (
            "https://graph.microsoft.com/v1.0/me/drive/root:/App/oplog/inst%20A/000001.ndjson:/content"
        )


class FakeGraphSession:
    """Graph 경로 주소지정을 모델링하는 in-memory fake."""

    _PREFIX = "https://graph.microsoft.com/v1.0/me/drive/root"

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.folders: set[str] = {""}

    def _parse(self, url):
        assert url.startswith(self._PREFIX), url
        rest = url[len(self._PREFIX) :]
        if rest == "":
            return ("root", "")
        if rest == "/children":
            return ("children", "")
        # ":/{enc}"(옵션 ":/content" | ":/children")
        assert rest.startswith(":/")
        rest = rest[2:]
        suffix = ""
        for suf in (":/content", ":/children", ":/createUploadSession"):
            if rest.endswith(suf):
                suffix = suf[1:]  # "/content"
                rest = rest[: -len(suf)]
                break
        path = "/".join(unquote(seg) for seg in rest.split("/"))
        return (suffix or "item", path)

    def _rel(self, full_path):
        # full_path 는 "App/..." — 앱 루트 제거 후 상대경로.
        parts = full_path.split("/", 1)
        return parts[1] if len(parts) > 1 else ""

    def request(self, method, url, headers=None, params=None, json=None, data=None, stream=False, timeout=None):
        if url.endswith("/me"):
            return FakeResp(200, {"userPrincipalName": "me@example.com"})
        kind, path = self._parse(url)
        if kind == "item" and method == "GET":
            if path in self.files:
                return FakeResp(200, {"id": path, "name": path.split("/")[-1],
                                      "size": len(self.files[path]), "file": {"hashes": {}}})
            return FakeResp(404)
        if kind == "item" and method == "DELETE":
            self.files.pop(path, None)
            return FakeResp(204)
        if kind == "/content" and method == "GET":
            if path in self.files:
                return FakeResp(200, content=self.files[path], text=self.files[path].decode())
            return FakeResp(404)
        if kind == "/content" and method == "PUT":
            self.files[path] = data if isinstance(data, bytes) else str(data).encode()
            return FakeResp(200, {"id": path, "name": path.split("/")[-1], "size": len(self.files[path]), "file": {}})
        if kind == "/children" and method == "GET":
            # path == "" → 앱 루트("App")의 children? 우리 walk 는 rel 기반.
            prefix = f"{path}/" if path else ""
            # path 는 "App" 또는 "App/media" 형태(앱 루트 포함).
            children = []
            seen = set()
            for fp in self.files:
                if fp.startswith(prefix) and fp != path:
                    tail = fp[len(prefix):]
                    seg = tail.split("/")[0]
                    full = f"{prefix}{seg}"
                    if full in seen:
                        continue
                    seen.add(full)
                    is_folder = "/" in tail
                    item = {"name": seg}
                    if is_folder:
                        item["folder"] = {}
                    else:
                        item.update({"id": full, "size": len(self.files[fp]), "file": {"hashes": {}}})
                    children.append(item)
            return FakeResp(200, {"value": children})
        if kind == "children" and method == "POST":  # 드라이브 루트 하위 폴더 생성
            return FakeResp(201, {"id": json.get("name")})
        if kind == "item" and method == "POST":  # 하위 children 생성은 :/children 로 옴
            return FakeResp(201, {"id": path})
        # POST .../children (하위 폴더)
        if kind == "/children" and method == "POST":
            return FakeResp(201, {"id": f"{path}/{json.get('name')}"})
        return FakeResp(404)


class TestOneDriveRoundTrip:
    def _provider(self):
        sess = FakeGraphSession()
        rc = RestClient(lambda: "tok", None, session=sess)
        return OneDriveProvider(secret_store=None, client_id="cid", root_name="App", rest=rc), sess

    def test_write_read_text(self):
        p, _ = self._provider()
        p.write_text("oplog/installs.json", '{"A": 3}')
        assert p.read_text("oplog/installs.json") == '{"A": 3}'
        assert p.read_text("missing.json") is None

    def test_account_name(self):
        p, _ = self._provider()
        assert p.account_name() == "me@example.com"

    def test_stat_and_delete(self):
        p, _ = self._provider()
        p.write_text("media/manifest.json", "x")
        rf = p.stat("media/manifest.json")
        assert rf is not None and rf.size == 1
        p.delete_file("media/manifest.json")
        assert p.stat("media/manifest.json") is None

    def test_list_files_prefix(self):
        p, _ = self._provider()
        p.write_text("oplog/A/000001.ndjson", "op1")
        p.write_text("oplog/A/000002.ndjson", "op2")
        p.write_text("media/manifest.json", "m")
        rels = sorted(rf.path for rf in p.list_files("oplog/"))
        assert rels == ["oplog/A/000001.ndjson", "oplog/A/000002.ndjson"]


# ---------------------------------------------------------------------------
# Google Drive — q 이스케이프 + 폴더트리 에뮬레이션 fake 왕복
# ---------------------------------------------------------------------------


class TestGDriveEscape:
    def test_q_escaping(self):
        assert _esc("a'b") == "a\\'b"
        assert _esc("a\\b") == "a\\\\b"


class FakeDriveSession:
    """Drive ID 모델을 모사하는 in-memory fake (folders/files, q 파싱)."""

    def __init__(self):
        self.items: dict[str, dict] = {}  # id → item
        self._n = 0
        self.upload_pending: dict[str, dict] = {}

    def _new_id(self, prefix="id"):
        self._n += 1
        return f"{prefix}{self._n}"

    def _match(self, q):
        m_parent = re.search(r"'([^']+)' in parents", q)
        parent = m_parent.group(1) if m_parent else None
        m_name = re.search(r"name='((?:[^'\\]|\\.)*)'", q)
        name = None
        if m_name:
            name = m_name.group(1).replace("\\'", "'").replace("\\\\", "\\")
        folder_mime = "application/vnd.google-apps.folder"
        want_folder = f"mimeType='{folder_mime}'" in q
        not_folder = f"mimeType!='{folder_mime}'" in q
        out = []
        for it in self.items.values():
            if parent and parent not in it.get("parents", []):
                continue
            if name is not None and it.get("name") != name:
                continue
            is_folder = it.get("mimeType") == folder_mime
            if want_folder and not is_folder:
                continue
            if not_folder and is_folder:
                continue
            out.append(it)
        return out

    def request(self, method, url, headers=None, params=None, json=None, data=None, stream=False, timeout=None):
        params = params or {}
        # resumable 업로드 init — /upload/... 가 /drive/v3/files 로 끝나므로 먼저 판별.
        if "/upload/drive/v3/files" in url and method in ("POST", "PATCH"):
            if method == "PATCH":
                m = re.search(r"/files/([^/?]+)", url)
                fid = m.group(1)
            else:
                fid = self._new_id("file")
                self.items[fid] = {
                    "id": fid, "name": json["name"], "mimeType": "application/octet-stream",
                    "parents": json.get("parents", []),
                }
            sess_uri = f"session://{fid}"
            self.upload_pending[sess_uri] = {"id": fid, "buf": b""}
            return FakeResp(200, headers={"Location": sess_uri})
        if url.endswith("/drive/v3/about"):
            return FakeResp(200, {"user": {"emailAddress": "me@gmail.com"}})
        if url.endswith("/drive/v3/files") and method == "GET":
            files = self._match(params.get("q", ""))
            return FakeResp(200, {"files": [self._proj(f) for f in files]})
        if url.endswith("/drive/v3/files") and method == "POST":  # 폴더 생성
            fid = self._new_id("fld")
            self.items[fid] = {
                "id": fid, "name": json["name"], "mimeType": json["mimeType"],
                "parents": json.get("parents", []),
            }
            return FakeResp(200, {"id": fid})
        m_get = re.search(r"/drive/v3/files/([^/?]+)$", url)
        if m_get and method == "GET" and params.get("alt") == "media":
            it = self.items.get(m_get.group(1))
            if not it:
                return FakeResp(404)
            content = it.get("content", b"")
            return FakeResp(200, content=content, text=content.decode())
        if m_get and method == "DELETE":
            self.items.pop(m_get.group(1), None)
            return FakeResp(204)
        return FakeResp(404)

    def put(self, url, data=None, headers=None, allow_redirects=True, timeout=None):
        pend = self.upload_pending.get(url)
        if pend is None:
            return FakeResp(404)
        pend["buf"] += data or b""
        it = self.items[pend["id"]]
        it["content"] = pend["buf"]
        it["size"] = len(pend["buf"])
        return FakeResp(200, {"id": it["id"], "name": it["name"], "size": it["size"]})

    @staticmethod
    def _proj(it):
        out = {"id": it["id"], "name": it["name"], "mimeType": it.get("mimeType")}
        if "size" in it:
            out["size"] = it["size"]
        return out


class TestGDriveRoundTrip:
    def _provider(self):
        sess = FakeDriveSession()
        rc = RestClient(lambda: "tok", None, session=sess)
        return GoogleDriveProvider(secret_store=None, root_name="App", rest=rc), sess

    def test_account_name(self):
        p, _ = self._provider()
        assert p.account_name() == "me@gmail.com"

    def test_write_read_text_creates_folder_tree(self):
        p, sess = self._provider()
        p.write_text("oplog/A/000001.ndjson", "hello-op")
        assert p.read_text("oplog/A/000001.ndjson") == "hello-op"
        # 앱루트 + oplog + A 폴더가 생성됐는지(경로→id 캐시).
        assert "" in p._folder_ids and "oplog" in p._folder_ids and "oplog/A" in p._folder_ids

    def test_folder_tree_reused_not_duplicated(self):
        p, sess = self._provider()
        p.write_text("oplog/A/1.ndjson", "a")
        p.write_text("oplog/A/2.ndjson", "b")
        folder_count = sum(
            1 for it in sess.items.values()
            if it.get("mimeType") == "application/vnd.google-apps.folder"
        )
        assert folder_count == 3  # App, oplog, A — 재사용

    def test_stat_and_delete(self):
        p, _ = self._provider()
        p.write_text("media/manifest.json", "xyz")
        rf = p.stat("media/manifest.json")
        assert rf is not None and rf.size == 3
        p.delete_file("media/manifest.json")
        assert p.stat("media/manifest.json") is None

    def test_list_files_prefix(self):
        p, _ = self._provider()
        p.write_text("oplog/A/1.ndjson", "a")
        p.write_text("oplog/A/2.ndjson", "b")
        p.write_text("media/manifest.json", "m")
        rels = sorted(rf.path for rf in p.list_files("oplog/"))
        assert rels == ["oplog/A/1.ndjson", "oplog/A/2.ndjson"]

    def test_overwrite_text_updates_same_file(self):
        p, sess = self._provider()
        p.write_text("oplog/installs.json", '{"A":1}')
        p.write_text("oplog/installs.json", '{"A":2}')
        assert p.read_text("oplog/installs.json") == '{"A":2}'
        files = [it for it in sess.items.values()
                 if it.get("name") == "installs.json"]
        assert len(files) == 1  # 새로 만들지 않고 덮어씀
