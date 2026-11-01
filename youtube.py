"""YouTube Data API v3: sign-in, upload, schedule, thumbnails and channel stats."""
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from core import APP_DIR, youtube_tags

SCOPES = ["https://www.googleapis.com/auth/youtube"]
TOKEN_FILE = APP_DIR / "youtube-token.json"


def client(client_secret, interactive=True):
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Not signed in to YouTube yet")
        if not client_secret:
            raise RuntimeError("Pick your client_secret.json in the YouTube tab first")
        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        # select_account makes Google show the channel picker (personal channel vs Brand Account) every time.
        creds = flow.run_local_server(port=0, open_browser=True, prompt="select_account consent",
                                      success_message="Signed in. You can close this tab and go back to Glowgills Studio.")
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def sign_out():
    TOKEN_FILE.unlink(missing_ok=True)


def _status(publish_at, privacy):
    status = {"selfDeclaredMadeForKids": True, "containsSyntheticMedia": True, "embeddable": True}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.isoformat()
    else:
        status["privacyStatus"] = privacy
    return status


def upload(yt, item, publish_at, privacy, log):
    body = {
        "snippet": {"title": item.title[:100], "description": item.description[:5000],
                    "tags": youtube_tags(item.tags), "categoryId": "1",
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": _status(publish_at, privacy),
    }
    media = MediaFileUpload(str(item.video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        progress, resp = req.next_chunk()
        if progress:
            log(f"  {item.name}: {int(progress.progress() * 100)}%")
    return resp["id"]


def set_thumbnail(yt, video_id, cover):
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(cover), mimetype="image/jpeg")).execute()


def reschedule(yt, video_id, publish_at):
    """Sets publishAt on a video that is still private. Returns False if it is already public."""
    cur = yt.videos().list(part="status", id=video_id).execute()["items"]
    if not cur:
        raise RuntimeError(f"video {video_id} not found on the channel")
    if cur[0]["status"]["privacyStatus"] != "private":
        return False
    yt.videos().update(part="status", body={"id": video_id, "status": _status(publish_at, "private")}).execute()
    return True


def _norm(t):
    return re.sub(r"\W+", " ", t).strip().lower()


def channel_uploads(yt):
    ch = yt.channels().list(part="contentDetails,snippet,statistics", mine=True).execute()["items"][0]
    playlist = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    videos, token = [], None
    while True:
        page = yt.playlistItems().list(part="snippet", playlistId=playlist, maxResults=50, pageToken=token).execute()
        videos += [(v["snippet"]["resourceId"]["videoId"], v["snippet"]["title"]) for v in page["items"]]
        token = page.get("nextPageToken")
        if not token:
            return ch, videos


def match_existing(yt, items):
    _, uploads = channel_uploads(yt)
    by_title = {_norm(t): vid for vid, t in uploads}
    return {it.name: by_title[_norm(it.title)] for it in items if _norm(it.title) in by_title}


def stats(yt):
    ch, uploads = channel_uploads(yt)
    s = ch["statistics"]
    lines = [f"{ch['snippet']['title']}: {s.get('subscriberCount', '?')} subscribers, "
             f"{s.get('viewCount', '0')} views, {s.get('videoCount', '0')} videos", ""]
    ids = [vid for vid, _ in uploads]
    rows = []
    for i in range(0, len(ids), 50):
        res = yt.videos().list(part="statistics,status,snippet", id=",".join(ids[i:i + 50])).execute()
        for v in res["items"]:
            st, vs = v["statistics"], v["status"]
            when = vs.get("publishAt", "")[:16].replace("T", " ")
            rows.append((int(st.get("viewCount", 0)), st.get("likeCount", "-"), vs["privacyStatus"], when, v["snippet"]["title"]))
    for views, likes, privacy, when, title in sorted(rows, reverse=True):
        extra = f" (goes live {when} UTC)" if when and privacy == "private" else ""
        lines.append(f"{views:>7} views {likes:>5} likes  {privacy:<8} {title}{extra}")
    return "\n".join(lines)
