from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
TOKEN = Path("token.json")


def get_creds() -> Credentials:
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if TOKEN.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        creds = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES).run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    return creds


creds = get_creds()
drive = build("drive", "v3", credentials=creds)
files = drive.files().list(
    q="mimeType='application/vnd.google-apps.document' and name contains 'CV'",
    fields="files(id, name)",
    pageSize=10,
).execute()["files"]
for f in files:
    print(f["id"], f["name"])