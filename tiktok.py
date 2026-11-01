"""TikTok Content Posting API: Login Kit sign-in (desktop PKCE), drafts upload and direct post."""
import hashlib
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from core import APP_DIR, load_json, save_json

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2/"
TOKEN_FILE = APP_DIR / "tiktok-token.json"
SCOPES = "user.info.basic,video.upload,video.publish"


def redirect_uri(port):
    return f"http://localhost:{port}/callback/"


def _token_request(data):
    r = requests.post(API + "oauth/token/", data=data, timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"TikTok sign-in failed: {j.get('error_description') or j}")
    j["expires_at"] = time.time() + int(j.get("expires_in", 0))
    save_json(TOKEN_FILE, j)
    return j


def sign_in(client_key, client_secret, port, log):
    if not (client_key and client_secret):
        raise RuntimeError("Enter the TikTok Client key and Client secret first")
    verifier = secrets.token_urlsafe(48)
    # TikTok's desktop Login Kit expects the SHA-256 code challenge hex-encoded.
    challenge = hashlib.sha256(verifier.encode()).hexdigest()
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Done. You can close this tab and go back to Glowgills Studio.</h2>")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", int(port)), Handler)
    server.timeout = 300
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_key": client_key, "scope": SCOPES, "response_type": "code",
        "redirect_uri": redirect_uri(port), "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    log("TikTok sign-in opened in your browser; waiting up to 5 minutes")
    server.handle_request()
    server.server_close()
    if got.get("state") != state or "code" not in got:
        raise RuntimeError(f"TikTok sign-in did not finish: {got.get('error_description') or got.get('error') or 'no answer'}")
    return _token_request({"client_key": client_key, "client_secret": client_secret, "code": got["code"],
                           "grant_type": "authorization_code", "redirect_uri": redirect_uri(port),
                           "code_verifier": verifier})


def access_token(client_key, client_secret):
    tok = load_json(TOKEN_FILE, None)
    if not tok:
        raise RuntimeError("Not signed in to TikTok yet")
    if tok["expires_at"] - time.time() < 300:
        tok = _token_request({"client_key": client_key, "client_secret": client_secret,
                              "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    return tok["access_token"]


def sign_out():
    TOKEN_FILE.unlink(missing_ok=True)


def _api(token, path, payload):
    r = requests.post(API + path, json=payload, timeout=60, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"})
    j = r.json()
    err = j.get("error") or {}
    if err.get("code") not in (None, "", "ok"):
        raise RuntimeError(f"TikTok: {err.get('code')} - {err.get('message')}")
    return j.get("data") or {}


def creator_info(token):
    return _api(token, "post/publish/creator_info/query/", {})


def post(token, path, caption, mode, privacy, log):
    """mode 'drafts' sends to the TikTok app inbox to finish there; 'direct' posts with `privacy`."""
    size = os.path.getsize(path)
    if size <= 64 * 1024 * 1024:
        chunk, count = size, 1
    else:
        chunk = 10 * 1024 * 1024
        count = size // chunk
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}
    if mode == "direct":
        data = _api(token, "post/publish/video/init/", {"source_info": source, "post_info": {
            "title": caption[:2200], "privacy_level": privacy, "is_aigc": True,
            "disable_comment": False, "disable_duet": False, "disable_stitch": False}})
    else:
        data = _api(token, "post/publish/inbox/video/init/", {"source_info": source})
    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            body = f.read(end - start + 1)
            r = requests.put(data["upload_url"], data=body, timeout=900, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code >= 300:
                raise RuntimeError(f"TikTok upload failed ({r.status_code}): {r.text[:300]}")
    log("  uploaded, waiting for TikTok")
    done = {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}
    for _ in range(60):
        st = _api(token, "post/publish/status/fetch/", {"publish_id": data["publish_id"]})
        if st.get("status") in done:
            return data["publish_id"], st["status"]
        if st.get("status") == "FAILED":
            raise RuntimeError(f"TikTok rejected the video: {st.get('fail_reason')}")
        time.sleep(5)
    return data["publish_id"], "PROCESSING"
