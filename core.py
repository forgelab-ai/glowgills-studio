"""Shared pieces: reading the numbered upload folder, schedules, captions, state and lint."""
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The title and hook linters come from separately licensed Claude skills and are not in the public repo.
# Copy title.py, hookscore.py and hooks.json next to this file (as yt_title.py, yt_hookscore.py) to enable them.
try:
    import yt_hookscore
    import yt_title
except ImportError:
    yt_hookscore = yt_title = None

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "GlowgillsStudio"
APP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "state.json"

DEFAULT_CONFIG = {
    "folder": r"D:\The Glowgills",
    "start_date": "",
    "time": "18:00",
    "utc_offset": "+03:30",
    "yt_client_secret": "",
    "meta_graph_version": "v23.0",
    "meta_page_id": "",
    "meta_page_token": "",
    "meta_ig_user_id": "",
    "tiktok_client_key": "",
    "tiktok_client_secret": "",
    "tiktok_port": "8723",
    "tiktok_mode": "drafts",
}

AI_LINE = "Made with AI: video and sound generated with MiniMax H3."

HASHTAGS = {
    "instagram": "#kidscartoon #axolotl #toddlers #preschool #cartoonforkids #glowgills",
    "facebook": "#kidscartoon #axolotl #preschool #glowgills",
    "tiktok": "#kidscartoon #axolotl #toddlers #preschool #animation #glowgills",
}


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_FILE, {}))
    return cfg


def save_config(cfg):
    save_json(CONFIG_FILE, cfg)


def load_state():
    state = load_json(STATE_FILE, {})
    state.setdefault("videos", {})
    state.setdefault("queue", [])
    return state


def save_state(state):
    save_json(STATE_FILE, state)


@dataclass
class Item:
    num: int
    name: str
    path: Path
    title: str
    description: str
    tags: list = field(default_factory=list)
    video: Path = None
    cover: Path = None


def parse_info(text):
    sections, current = {}, None
    for line in text.splitlines():
        if line.strip() in ("TITLE", "DESCRIPTION", "TAGS"):
            current = line.strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
    get = lambda k: "\n".join(sections.get(k, [])).strip()
    tags = [t.strip() for t in get("TAGS").replace("\n", ",").split(",") if t.strip()]
    return get("TITLE"), get("DESCRIPTION"), tags


def load_folder(root):
    items = []
    root = Path(root)
    if not root.is_dir():
        return items
    for d in sorted(root.iterdir()):
        m = re.match(r"^(\d+)\s*-", d.name)
        if not (d.is_dir() and m):
            continue
        video = d / "video.mp4"
        info = d / "upload-info.txt"
        if not (video.exists() and info.exists()):
            continue
        title, desc, tags = parse_info(info.read_text(encoding="utf-8-sig"))
        cover = d / "cover.jpg"
        items.append(Item(int(m.group(1)), d.name, d, title, desc, tags, video,
                          cover if cover.exists() else None))
    return items


def parse_offset(text):
    m = re.fullmatch(r"\s*([+-])(\d{1,2}):?(\d{2})\s*", text or "")
    if not m:
        raise ValueError(f"UTC offset must look like +03:30, not {text!r}")
    sign = 1 if m.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def schedule(count, start_date, hhmm, offset):
    """One slot a day at the same local time, starting on start_date (YYYY-MM-DD)."""
    tz = parse_offset(offset)
    day = datetime.strptime(start_date.strip(), "%Y-%m-%d")
    h, m = (int(x) for x in hhmm.strip().split(":"))
    first = day.replace(hour=h, minute=m, tzinfo=tz)
    return [first + timedelta(days=i) for i in range(count)]


def social_caption(item, platform):
    paragraphs = [p.strip() for p in item.description.split("\n\n") if p.strip()]
    story = paragraphs[0] if paragraphs else ""
    ai = next((p for p in paragraphs if "Made with AI" in p), AI_LINE)
    title = re.sub(r"\s*\|\s*The Glowgills\s*#shorts\s*$", "", item.title).strip()
    return f"{title}\n\n{story}\n\n{ai}\n\n{HASHTAGS[platform]}"


def youtube_tags(tags):
    out, total = [], 0
    for t in tags:
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if total + cost > 480:
            break
        out.append(t)
        total += cost
    return out


def lint(item):
    if yt_title is None:
        return "-", "-", f'Title: "{item.title}"\n  (title and hook linters not installed)'
    t = yt_title.check(item.title, None)
    _, hook, formula, _ = yt_hookscore.score(item.title)
    lines = [f'Title: "{item.title}"', f"  title score {t['score']}/100, hook score {hook} ({yt_hookscore.band(hook)}, {formula})"]
    lines += [f"  + {g}" for g in t["good"]]
    lines += [f"  - {kind}: {msg}" for kind, msg in t["issues"]]
    return t["score"], hook, "\n".join(lines)


def export_packs(items, root, log):
    out = Path(root) / "_social-packs"
    for platform in ("instagram", "tiktok", "facebook"):
        for it in items:
            d = out / platform / it.name
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(it.video, d / "video.mp4")
            if it.cover:
                shutil.copy2(it.cover, d / "cover.jpg")
            (d / "caption.txt").write_text(social_caption(it, platform), encoding="utf-8")
        log(f"{platform}: {len(items)} folders written")
    return out
