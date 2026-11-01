# Glowgills Studio

A Windows desktop app that publishes a folder of short videos to **YouTube, Instagram, Facebook and TikTok** from one window: it uploads, schedules one video a day, sets thumbnails, and shows channel stats.

I built it to run my AI-generated kids' cartoon channel, *The Glowgills*, where a new episode goes out every day on four platforms. Doing that by hand meant about 30 minutes a day of copy-pasting; with this app it's one click.

## What it does

- **Reads a numbered folder**, one subfolder per video (`01 - Trailer/`, `02 - Episode 1/` …), each holding `video.mp4`, an optional `cover.jpg`, and `upload-info.txt` with the title, description and tags.
- **YouTube** (Data API v3, OAuth desktop flow): uploads, schedules one video a day at a fixed local time, marks "made for kids", adds the AI-content disclosure, sets custom thumbnails, can reschedule videos already on the channel, and shows channel and per-video stats.
- **Facebook Page Reels** (Meta Graph API): uploads with native scheduling.
- **Instagram Reels** (Meta Graph API): Instagram's API has no scheduling, so the app keeps its own queue and publishes each item when it's due, catching up on the next launch if the PC was off.
- **TikTok** (Content Posting API with Login Kit, desktop PKCE): sends to drafts or posts directly.
- **Social packs**: exports a ready-made folder per platform (video, cover, caption with hashtags) for manual posting.
- **Safety checks**: asks for confirmation before every publish, keeps credentials outside the project folder, and never stores secrets in the repo.

## Tech

Python 3.13 · Tkinter · Google API client · Meta Graph API · TikTok Content Posting API · PyInstaller (single `.exe`)

```
app.py       the window: tabs, video table, publish queue
core.py      folder parsing, schedules, captions, config and state
youtube.py   YouTube upload, schedule, thumbnails, stats
meta.py      Instagram and Facebook Reels with resumable upload
tiktok.py    TikTok sign-in (local callback server) and posting
```

## Run it

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

Build the single-file exe:

```bash
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller GlowgillsStudio.spec
```

Each platform needs your own developer credentials: a Google Cloud OAuth desktop client, a Meta app with a Page token, and a TikTok developer app. The app stores them in `%APPDATA%\GlowgillsStudio`, never in this folder.

## Notes

- Until Google audits your Cloud project, videos uploaded through the API stay private. The app works around this: upload in YouTube Studio, then let it find and reschedule the videos.
- Built with Claude Code as a pair programmer.

## License

MIT
