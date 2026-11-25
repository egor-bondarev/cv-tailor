import itertools

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

import cvtailor.google_api as gapi
from cvtailor.google_api import AccessDenied, AuthRequired, GoogleClient

OUT = "out-folder"
BASE = "base-resume"


def http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"error")


class _Req:
    def __init__(self, fake, method, fn):
        self.fake, self.method, self.fn = fake, method, fn

    def execute(self):
        self.fake.calls.append(self.method)
        queue = self.fake.errors.get(self.method, [])
        if queue:
            raise queue.pop(0)
        return self.fn()


class FakeGoogle:
    """Fake docs + drive services sharing one file tree."""

    def __init__(self):
        self.files = {
            OUT: {"name": "out", "parents": ["root"], "mimeType": "folder"},
            BASE: {"name": "Base CV", "parents": ["resumes"], "mimeType": "doc"},
            "other": {"name": "Other doc", "parents": ["root"], "mimeType": "doc"},
            "resume-in-out": {"name": "Base 2", "parents": [OUT], "mimeType": "doc"},
        }
        self.calls, self.errors, self.updates, self.doc_kwargs = [], {}, [], []
        self._ids = (f"new-{i}" for i in itertools.count(1))

    # docs service
    def documents(self):
        return self

    def get(self, documentId, **kw):
        self.doc_kwargs.append(kw)
        return _Req(self, "docs.get", lambda: {"documentId": documentId, "revisionId": "r1", "body": {"content": []}})

    def batchUpdate(self, documentId, body):
        return _Req(self, "docs.batchUpdate", lambda: self.updates.append((documentId, body)) or {"ok": True})

    # drive service
    def drive(self):
        return _Drive(self)


class _Drive:
    def __init__(self, fake):
        self.f = fake

    def files(self):
        return self

    def get(self, fileId, fields):
        return _Req(self.f, "drive.get", lambda: {"id": fileId, "parents": self.f.files.get(fileId, {}).get("parents", [])})

    def list(self, q, fields, **kw):
        parent = q.split("'")[1]
        folder = "folder" in q
        items = [
            {"id": i, "name": f["name"]}
            for i, f in self.f.files.items()
            if parent in f["parents"] and (f["mimeType"] == "folder") == folder
        ]
        return _Req(self.f, "drive.list", lambda: {"files": items})

    def create(self, body, fields):
        def run():
            fid = next(self.f._ids)
            self.f.files[fid] = {"name": body["name"], "parents": body["parents"], "mimeType": "folder"}
            return {"id": fid}
        return _Req(self.f, "drive.create", run)

    def copy(self, fileId, body, fields):
        def run():
            fid = next(self.f._ids)
            self.f.files[fid] = {"name": body["name"], "parents": body["parents"], "mimeType": "doc"}
            return {"id": fid}
        return _Req(self.f, "drive.copy", run)

    def update(self, fileId, body, fields=None):
        def run():
            self.f.files[fileId]["name"] = body["name"]
            return {"id": fileId}
        return _Req(self.f, "drive.update", run)


@pytest.fixture
def fake():
    return FakeGoogle()


def client(fake, sleeps=None):
    return GoogleClient(fake, fake.drive(), {BASE, "resume-in-out"}, OUT, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_get_doc_preview_passes_view_mode(fake):
    client(fake).get_doc(BASE, preview_accepted=True)
    assert fake.doc_kwargs[-1] == {"suggestionsViewMode": "PREVIEW_SUGGESTIONS_ACCEPTED"}
    client(fake).get_doc(BASE)
    assert fake.doc_kwargs[-1] == {}


def test_get_doc_denied_for_unrelated_id(fake):
    with pytest.raises(AccessDenied, match="other"):
        client(fake).get_doc("other")


def test_batch_update_denied_for_base_resume(fake):
    with pytest.raises(AccessDenied):
        client(fake).batch_update("resume-in-out", {"requests": []})
    with pytest.raises(AccessDenied):
        client(fake).batch_update(BASE, {"requests": []})


def test_copy_denied_for_source_not_in_allowed(fake):
    with pytest.raises(AccessDenied):
        client(fake).copy_doc("other", "x", OUT)


def test_copy_then_batch_update_allowed(fake):
    c = client(fake)
    folder = c.create_folder("Acme", OUT)
    copy = c.copy_doc(BASE, "Senior SDET - Acme", folder)
    c.batch_update(copy, {"requests": [1]})
    assert fake.updates == [(copy, {"requests": [1]})]
    assert c.list_doc_names(folder) == {"Senior SDET - Acme"}
    assert ("new-1", "Acme") in c.list_folders(OUT)


def test_fresh_client_can_read_and_rename_earlier_copy(fake):
    folder = client(fake).create_folder("Acme", OUT)
    copy = client(fake).copy_doc(BASE, "CV", folder)
    fresh = client(fake)
    fresh.get_doc(copy)
    fresh.batch_update(copy, {"requests": []})
    fresh.rename(copy, "[FAILED] CV")
    assert fake.files[copy]["name"] == "[FAILED] CV"


def test_create_folder_outside_output_denied(fake):
    with pytest.raises(AccessDenied):
        client(fake).create_folder("x", "root")


def test_read_retries_on_503_and_timeout(fake):
    sleeps = []
    fake.errors["docs.get"] = [http_error(503), TimeoutError()]
    client(fake, sleeps).get_doc(BASE)
    assert sleeps == [1, 2]


def test_write_not_retried_on_503(fake):
    c = client(fake)
    copy = c.copy_doc(BASE, "CV", OUT)
    fake.errors["docs.batchUpdate"] = [http_error(503)]
    with pytest.raises(HttpError):
        c.batch_update(copy, {"requests": []})
    assert fake.calls.count("docs.batchUpdate") == 1


def test_write_retried_on_429(fake):
    sleeps = []
    c = client(fake, sleeps)
    fake.errors["drive.copy"] = [http_error(429)]
    c.copy_doc(BASE, "CV", OUT)
    assert fake.calls.count("drive.copy") == 2 and sleeps == [1]


def test_no_retry_on_400(fake):
    fake.errors["docs.get"] = [http_error(400)]
    with pytest.raises(HttpError):
        client(fake).get_doc(BASE)
    assert fake.calls.count("docs.get") == 1


def test_gives_up_after_five_attempts(fake):
    sleeps = []
    fake.errors["docs.get"] = [http_error(503)] * 5
    with pytest.raises(HttpError):
        client(fake, sleeps).get_doc(BASE)
    assert sleeps == [1, 2, 4, 8]


def test_refresh_error_raises_auth_required_and_deletes_token(tmp_path, monkeypatch):
    (tmp_path / "token.json").write_text("{}")

    class Creds:
        valid = False
        expired = True
        refresh_token = "x"

        def refresh(self, request):
            raise RefreshError("invalid_grant")

    monkeypatch.setattr(gapi.Credentials, "from_authorized_user_file", lambda *a, **k: Creds())
    with pytest.raises(AuthRequired):
        GoogleClient.from_token(tmp_path, {BASE}, OUT)
    assert not (tmp_path / "token.json").exists()


def test_missing_token_raises_auth_required(tmp_path):
    with pytest.raises(AuthRequired):
        GoogleClient.from_token(tmp_path, {BASE}, OUT)


def test_mid_run_refresh_error_becomes_auth_required(fake, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}")
    c = GoogleClient(fake, fake.drive(), {BASE}, OUT, sleep=lambda s: None, token_path=token)
    fake.errors["docs.get"] = [RefreshError("invalid_grant")]
    with pytest.raises(AuthRequired):
        c.get_doc(BASE)
    assert not token.exists()


def test_401_becomes_auth_required(fake, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}")
    c = GoogleClient(fake, fake.drive(), {BASE}, OUT, sleep=lambda s: None, token_path=token)
    fake.errors["docs.get"] = [http_error(401)]
    with pytest.raises(AuthRequired):
        c.get_doc(BASE)
    assert not token.exists()


def test_drive_rate_limit_403_retried_for_writes(fake):
    sleeps = []
    c = client(fake, sleeps)
    err = HttpError(httplib2.Response({"status": 403}), b'{"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}')
    fake.errors["drive.copy"] = [err]
    c.copy_doc(BASE, "CV", OUT)
    assert sleeps == [1]


def test_plain_403_not_retried(fake):
    fake.errors["docs.get"] = [http_error(403)]
    with pytest.raises(HttpError):
        client(fake).get_doc(BASE)
    assert fake.calls.count("docs.get") == 1


def test_read_retries_on_dns_and_os_errors(fake):
    sleeps = []
    fake.errors["docs.get"] = [httplib2.ServerNotFoundError("dns"), OSError("reset")]
    client(fake, sleeps).get_doc(BASE)
    assert sleeps == [1, 2]
