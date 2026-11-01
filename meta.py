"""Instagram Reels and Facebook Page Reels through the Meta Graph API (local file upload)."""
import os
import time

import requests

GRAPH = "https://graph.facebook.com/"


def _check(r):
    try:
        j = r.json()
    except ValueError:
        r.raise_for_status()
        return {}
    if r.status_code >= 400 or (isinstance(j, dict) and "error" in j):
        err = j.get("error", {}) if isinstance(j, dict) else {}
        raise RuntimeError(err.get("error_user_msg") or err.get("message") or r.text)
    return j


def _upload(url, token, path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        return _check(requests.post(url, data=f, timeout=900, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}))


def find_accounts(ver, page_id, token):
    j = _check(requests.get(f"{GRAPH}{ver}/{page_id}", timeout=30, params={
        "fields": "name,instagram_business_account{id,username}", "access_token": token}))
    ig = j.get("instagram_business_account") or {}
    return j.get("name", ""), ig.get("id", ""), ig.get("username", "")


def instagram_reel(ver, ig_id, token, path, caption, log):
    j = _check(requests.post(f"{GRAPH}{ver}/{ig_id}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "share_to_feed": "true", "access_token": token}))
    cid = j["id"]
    _upload(j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{ver}/{cid}", token, path)
    log("  uploaded, waiting for Instagram to process it")
    for _ in range(120):
        st = _check(requests.get(f"{GRAPH}{ver}/{cid}", timeout=30, params={
            "fields": "status_code,status", "access_token": token}))
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the video: {st.get('status')}")
        time.sleep(5)
    else:
        raise RuntimeError("Instagram is still processing after 10 minutes; try again later")
    return _check(requests.post(f"{GRAPH}{ver}/{ig_id}/media_publish", timeout=60, data={
        "creation_id": cid, "access_token": token}))["id"]


def facebook_reel(ver, page_id, token, path, description, when=None):
    """Publishes now, or schedules natively on Facebook when `when` (aware datetime) is given."""
    j = _check(requests.post(f"{GRAPH}{ver}/{page_id}/video_reels", timeout=60, data={
        "upload_phase": "start", "access_token": token}))
    vid = j["video_id"]
    _upload(j.get("upload_url") or f"https://rupload.facebook.com/video-upload/{ver}/{vid}", token, path)
    data = {"upload_phase": "finish", "video_id": vid, "description": description, "access_token": token}
    if when:
        data.update(video_state="SCHEDULED", scheduled_publish_time=str(int(when.timestamp())))
    else:
        data["video_state"] = "PUBLISHED"
    _check(requests.post(f"{GRAPH}{ver}/{page_id}/video_reels", timeout=60, data=data))
    return vid
