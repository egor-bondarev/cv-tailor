"""Thin Google Docs/Drive client with folder-based access guards (DESIGN.md §9)."""

from __future__ import annotations

import time

import httplib2
from pathlib import Path
from typing import Callable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
RETRY_STATUSES = {429, 500, 502, 503, 504}
PAUSES = (1, 2, 4, 8)
MAX_PARENT_DEPTH = 3


class AuthRequired(RuntimeError):
    pass


class AccessDenied(RuntimeError):
    pass


def login(repo_dir: Path) -> None:
    flow = InstalledAppFlow.from_client_secrets_file(str(repo_dir / "credentials.json"), SCOPES)
    creds = flow.run_local_server(port=0)
    (repo_dir / "token.json").write_text(creds.to_json())


def _status(exc: Exception) -> int | None:
    return exc.resp.status if isinstance(exc, HttpError) else None


def _rate_limited(exc: Exception) -> bool:
    """Drive signals rate limits as 403 rateLimitExceeded / userRateLimitExceeded."""
    if not isinstance(exc, HttpError) or exc.resp.status != 403:
        return False
    content = exc.content or b""
    return b"rateLimitExceeded" in content or b"RateLimitExceeded" in content


class GoogleClient:
    def __init__(
        self,
        docs,
        drive,
        allowed_docs: set[str],
        output_folder_id: str,
        sleep: Callable[[float], None] = time.sleep,
        token_path: Path | None = None,
    ):
        self.docs, self.drive = docs, drive
        self.allowed_docs = set(allowed_docs)
        self.output_folder_id = output_folder_id
        self.sleep = sleep
        self.token_path = token_path
        self._in_output: dict[str, bool] = {output_folder_id: True}

    @classmethod
    def from_token(cls, repo_dir: Path, allowed_docs: set[str], output_folder_id: str) -> "GoogleClient":
        token = repo_dir / "token.json"
        if not token.exists():
            raise AuthRequired("no token.json: sign in to Google first")
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        if not creds.valid:
            if not (creds.expired and creds.refresh_token):
                token.unlink(missing_ok=True)
                raise AuthRequired("token is invalid: sign in to Google again")
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                token.unlink(missing_ok=True)
                raise AuthRequired(f"token expired or revoked ({exc}): sign in to Google again") from None
            token.write_text(creds.to_json())
        docs = build("docs", "v1", credentials=creds, cache_discovery=False)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        return cls(docs, drive, allowed_docs, output_folder_id, token_path=token)

    # --- plumbing -----------------------------------------------------------

    def _auth_failed(self, exc: Exception) -> AuthRequired:
        if self.token_path is not None:
            self.token_path.unlink(missing_ok=True)
        return AuthRequired(f"Google rejected the token ({exc}): sign in again")

    def _call(self, request, write: bool = False):
        attempt = 0
        while True:
            try:
                return request.execute()
            except RefreshError as exc:
                raise self._auth_failed(exc) from None
            except (HttpError, OSError, httplib2.HttpLib2Error) as exc:
                status = _status(exc)
                if status == 401:
                    raise self._auth_failed(exc) from None
                not_executed = status == 429 or _rate_limited(exc)
                retryable = not_executed if write else (not_executed or status in RETRY_STATUSES or status is None)
                if not retryable or attempt >= len(PAUSES):
                    raise
                self.sleep(PAUSES[attempt])
                attempt += 1

    def in_output(self, file_id: str, depth: int = MAX_PARENT_DEPTH) -> bool:
        if file_id in self._in_output:
            return self._in_output[file_id]
        result = False
        if depth > 0 and file_id != "root":
            try:
                parents = self._call(self.drive.files().get(fileId=file_id, fields="parents")).get("parents", [])
            except HttpError as exc:
                if _status(exc) not in (403, 404):
                    raise
                parents = []
            result = any(p == self.output_folder_id or self.in_output(p, depth - 1) for p in parents)
        self._in_output[file_id] = result
        return result

    def _require(self, ok: bool, method: str, file_id: str) -> None:
        if not ok:
            raise AccessDenied(f"{method}: access to {file_id} is not allowed")

    def _require_output(self, method: str, folder_id: str) -> None:
        self._require(folder_id == self.output_folder_id or self.in_output(folder_id), method, folder_id)

    def _list(self, query: str) -> list[dict]:
        items, token = [], None
        while True:
            kw = {"pageToken": token} if token else {}
            resp = self._call(self.drive.files().list(q=query, fields="nextPageToken, files(id, name)", pageSize=100, **kw))
            items += resp.get("files", [])
            token = resp.get("nextPageToken")
            if not token:
                return items

    # --- API ----------------------------------------------------------------

    def get_doc(self, doc_id: str, preview_accepted: bool = False) -> dict:
        self._require(doc_id in self.allowed_docs or self.in_output(doc_id), "get_doc", doc_id)
        kw = {"suggestionsViewMode": "PREVIEW_SUGGESTIONS_ACCEPTED"} if preview_accepted else {}
        return self._call(self.docs.documents().get(documentId=doc_id, **kw))

    def list_folders(self, parent_id: str) -> list[tuple[str, str]]:
        self._require_output("list_folders", parent_id)
        q = f"'{parent_id}' in parents and mimeType='{FOLDER_MIME}' and trashed=false"
        return [(f["id"], f["name"]) for f in self._list(q)]

    def list_doc_names(self, folder_id: str) -> set[str]:
        self._require_output("list_doc_names", folder_id)
        q = f"'{folder_id}' in parents and mimeType='{DOC_MIME}' and trashed=false"
        return {f["name"] for f in self._list(q)}

    def create_folder(self, name: str, parent_id: str) -> str:
        self._require_output("create_folder", parent_id)
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        fid = self._call(self.drive.files().create(body=body, fields="id"), write=True)["id"]
        self._in_output[fid] = True
        return fid

    def copy_doc(self, doc_id: str, name: str, parent_id: str) -> str:
        self._require(doc_id in self.allowed_docs, "copy_doc (source)", doc_id)
        self._require_output("copy_doc", parent_id)
        body = {"name": name, "parents": [parent_id]}
        fid = self._call(self.drive.files().copy(fileId=doc_id, body=body, fields="id"), write=True)["id"]
        self._in_output[fid] = True
        return fid

    def _require_writable(self, method: str, file_id: str) -> None:
        self._require(file_id not in self.allowed_docs and self.in_output(file_id), method, file_id)

    def batch_update(self, doc_id: str, body: dict) -> dict:
        self._require_writable("batch_update", doc_id)
        return self._call(self.docs.documents().batchUpdate(documentId=doc_id, body=body), write=True)

    def add_comment(self, file_id: str, text: str, quote: str | None = None) -> str:
        """A file-level comment: the Drive API cannot anchor comments to text inside a Google Doc,
        so the quote is shown as the comment's quoted content instead."""
        self._require_writable("add_comment", file_id)
        body: dict = {"content": text}
        if quote:
            body["quotedFileContent"] = {"mimeType": "text/plain", "value": quote}
        return self._call(self.drive.comments().create(fileId=file_id, body=body, fields="id"), write=True)["id"]

    def export_pdf(self, file_id: str) -> bytes:
        """The document rendered by Google, for page layout checks."""
        self._require(file_id in self.allowed_docs or self.in_output(file_id), "export_pdf", file_id)
        return self._call(self.drive.files().export(fileId=file_id, mimeType="application/pdf"))

    def create_doc(self, name: str, parent_id: str) -> str:
        """An empty Google Doc in an output folder (the cover letter, v2 V6)."""
        self._require_output("create_doc", parent_id)
        body = {"name": name, "mimeType": DOC_MIME, "parents": [parent_id]}
        fid = self._call(self.drive.files().create(body=body, fields="id"), write=True)["id"]
        self._in_output[fid] = True
        return fid

    def upload_pdf(self, name: str, parent_id: str, data: bytes, file_id: str | None = None) -> str:
        """Upload a PDF to an output folder, or replace the content of an earlier upload `file_id`."""
        from googleapiclient.http import MediaInMemoryUpload

        media = MediaInMemoryUpload(data, mimetype="application/pdf", resumable=False)
        if file_id:
            self._require_writable("upload_pdf", file_id)
            req = self.drive.files().update(fileId=file_id, body={"name": name}, media_body=media, fields="id")
            return self._call(req, write=True)["id"]
        self._require_output("upload_pdf", parent_id)
        req = self.drive.files().create(body={"name": name, "parents": [parent_id]}, media_body=media, fields="id")
        fid = self._call(req, write=True)["id"]
        self._in_output[fid] = True
        return fid

    def rename(self, file_id: str, name: str) -> None:
        self._require_writable("rename", file_id)
        self._call(self.drive.files().update(fileId=file_id, body={"name": name}, fields="id"), write=True)
