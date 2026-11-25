# Google Cloud setup for cv-tailor (OAuth)

`cvtailor` talks to Google Docs and Drive through your own OAuth client. Everything here is free: no billing account or credit card is needed.

Time: 30–60 minutes, once.

## 1. Project

1. Open <https://console.cloud.google.com/> and sign in with **the Google account that can open your resumes**. Tailored copies will be owned by this account.
2. Project picker (top left) → **New project**.
3. Name it, for example, `cv-tailor`. Organization: `No organization`. **Create**.
4. Make sure the new project is selected in the header.

If the console offers to enable billing or a free trial, close it: you don't need it.

## 2. Enable the APIs

1. **Menu → APIs & Services → Library**.
2. Search for **Google Docs API** → **Enable**.
3. Back in Library, search for **Google Drive API** → **Enable**.

## 3. Consent screen (Google Auth Platform)

1. **Menu → Google Auth platform → Branding**. If you see "Google Auth platform not configured yet", click **Get Started**.
2. **App Information**: App name `cv-tailor`, User support email: your address. **Next**.
3. **Audience**: choose **External**. "Internal" exists only for Google Workspace organizations. **Next**.
4. **Contact Information**: your email. **Next**.
5. **Finish**: accept the User Data Policy → **Continue** → **Create**.
6. **Data Access → Add or remove scopes**. Add:
   - `https://www.googleapis.com/auth/documents`
   - `https://www.googleapis.com/auth/drive`

   **Update** → **Save**. The narrower `drive.file` scope is not enough: it only sees files the app created, and the tool must read and copy your existing resumes.
7. **Audience**: keep the publishing status **Testing** and add your email under **Test users**. Without this, sign-in is blocked.

The cost of Testing: the refresh token expires after 7 days. When it does, `cvtailor` gets `invalid_grant`, deletes `token.json`, and opens the browser to sign in again. That's one click a week.

Why not **Publish app**: publishing requires a home page, a privacy policy link, and an authorized domain on the Branding page, which is extra work for a personal tool. If you still want to publish:
- don't upload a **logo**: an app with a logo must go through Google verification;
- **Application home page**: a GitHub Pages page, for example `https://<user>.github.io/cv-tailor/`;
- **Privacy policy**: a page next to it with 3–4 sentences, for example: "no data is collected, stored, or shared; the app runs locally and only accesses its owner's documents";
- **Authorized domains**: `<user>.github.io`;
- **Terms of service**: optional.

Either way you don't need Google verification. At sign-in you'll see "Google hasn't verified this app": click **Advanced** → **Go to cv-tailor (unsafe)**. It's your own app, so the warning is expected.

## 4. OAuth client

1. **Menu → Google Auth platform → Clients → Create Client**.
2. Application type: **Desktop app**. A Web application client fails with `redirect_uri_mismatch`.
3. Name: `cv-tailor-cli`. Only you see it, in the console.
4. Leave "Use this client for an AI-powered agent" unchecked. The script calls Google itself, and this setting can't be changed later.
5. **Create**. Redirect URIs aren't needed for Desktop apps.
6. In the dialog, click **Download JSON**. If you closed it, open **Clients** → your client and download it there.
7. Save the file as `credentials.json` in the repository root. It's git-ignored: never commit or share it.

## 5. Check

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
python scripts/google_check.py
```

On the first run a browser opens: pick the account, get past the "unverified app" screen, and click **Allow**. The script saves `token.json` (also git-ignored) and prints Google Docs whose names contain `CV`. Later runs don't open the browser.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Access blocked: cv-tailor has not completed the Google verification process` | The app is in Testing and your email is not in Test users |
| `invalid_grant` after a week | Expected in Testing: delete `token.json` and sign in again (`cvtailor` does this for you) |
| `insufficient authentication scopes` | Scopes in the code and in the token differ: delete `token.json` |
| Empty file list | Signed in with the wrong account: delete `token.json` and sign in with the account that owns or can open the resumes |
| `API has not been used in project … or it is disabled` | Docs API or Drive API not enabled (step 2) |

## Security

- `credentials.json` and `token.json` give access to your whole Drive. Keep them local only.
- To revoke access: <https://myaccount.google.com/permissions> → cv-tailor → **Remove access**.
