"""Glowgills Studio: one window to send the numbered episode folder to YouTube, Instagram, Facebook and TikTok."""
import os
import queue
import sys
import threading
import traceback
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import core
import meta
import tiktok
import youtube

PLATFORMS = ("youtube", "instagram", "facebook", "tiktok")
LICENSE_NOTE = ("MiniMax H3 license: don't publish while you are in the EU (e.g. Hungary), the UK, "
                "South Korea or the USA.\n\nAre you somewhere else right now (Iran, Turkey, Georgia...)?")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Glowgills Studio")
        self.geometry("1100x760")
        self.minsize(900, 600)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "icon.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
        self.cfg = core.load_config()
        if not self.cfg["start_date"]:
            self.cfg["start_date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.state_ = core.load_state()
        self.items = []
        self.vars = {}
        self.msgs = queue.Queue()
        self.busy = False
        self.license_ok = False
        self.queue_hint_shown = False
        self.snap = {"sel": set(), "privacy": "SELF_ONLY", "ig": True, "fb": True}
        self._build()
        self.reload()
        self.after(100, self._pump)
        self.after(60_000, self._run_queue)

    # ---------- layout ----------
    def var(self, key):
        if key not in self.vars:
            self.vars[key] = tk.StringVar(value=self.cfg.get(key, ""))
        return self.vars[key]

    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Episode folder:").pack(side="left")
        ttk.Entry(top, textvariable=self.var("folder"), width=60).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(top, text="Browse...", command=self._pick_folder).pack(side="left")
        ttk.Button(top, text="Reload", command=self.reload).pack(side="left", padx=4)

        sched = ttk.Frame(self, padding=(8, 0))
        sched.pack(fill="x")
        ttk.Label(sched, text="One a day starting").pack(side="left")
        ttk.Entry(sched, textvariable=self.var("start_date"), width=11).pack(side="left", padx=4)
        ttk.Label(sched, text="at").pack(side="left")
        ttk.Entry(sched, textvariable=self.var("time"), width=6).pack(side="left", padx=4)
        ttk.Label(sched, text="UTC offset").pack(side="left")
        ttk.Entry(sched, textvariable=self.var("utc_offset"), width=7).pack(side="left", padx=4)
        ttk.Label(sched, text="(Tehran is +03:30)  Select rows below; the order of the numbers sets the order.",
                  foreground="#666").pack(side="left", padx=8)

        cols = ("title", "score") + PLATFORMS
        self.tree = ttk.Treeview(self, columns=cols, height=10, selectmode="extended")
        self.tree.heading("#0", text="Folder")
        self.tree.column("#0", width=290)
        self.tree.heading("title", text="Title")
        self.tree.column("title", width=330)
        self.tree.heading("score", text="Title/Hook")
        self.tree.column("score", width=75, anchor="center")
        for p in PLATFORMS:
            self.tree.heading(p, text=p.capitalize())
            self.tree.column(p, width=95, anchor="center")
        self.tree.pack(fill="x", padx=8, pady=6)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_lint())

        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        nb = ttk.Notebook(pane)
        pane.add(nb, weight=3)
        self.log_box = tk.Text(pane, height=8, wrap="word", font=("Consolas", 9))
        pane.add(self.log_box, weight=2)

        nb.add(self._tab_titles(nb), text="Check titles")
        nb.add(self._tab_youtube(nb), text="YouTube")
        nb.add(self._tab_meta(nb), text="Instagram + Facebook")
        nb.add(self._tab_tiktok(nb), text="TikTok")
        nb.add(self._tab_packs(nb), text="Social packs")
        nb.add(self._tab_queue(nb), text="Queue")

    def _row(self, parent, label, key, width=50, show=None):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=22).pack(side="left")
        e = ttk.Entry(f, textvariable=self.var(key), width=width, show=show)
        e.pack(side="left", fill="x", expand=True)
        return f

    def _buttons(self, parent, *specs):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=6)
        for text, cmd in specs:
            ttk.Button(f, text=text, command=cmd).pack(side="left", padx=(0, 6))
        return f

    def _note(self, parent, text):
        ttk.Label(parent, text=text, foreground="#666", wraplength=950, justify="left").pack(fill="x", pady=(4, 0))

    def _tab_titles(self, nb):
        f = ttk.Frame(nb, padding=8)
        self.lint_box = tk.Text(f, wrap="word", font=("Consolas", 9))
        self.lint_box.pack(fill="both", expand=True)
        return f

    def _tab_youtube(self, nb):
        f = ttk.Frame(nb, padding=8)
        row = self._row(f, "client_secret.json", "yt_client_secret")
        ttk.Button(row, text="Pick...", command=self._pick_secret).pack(side="left", padx=4)
        self._buttons(f, ("Sign in", lambda: self.task(self._yt_signin)),
                      ("Sign out", self._yt_signout),
                      ("Channel stats", lambda: self.task(self._yt_stats)))
        self._buttons(f, ("Upload selected + schedule", lambda: self.task(self._yt_upload, publish=True)),
                      ("Find selected on my channel", lambda: self.task(self._yt_link)),
                      ("Reschedule selected (already on channel)", lambda: self.task(self._yt_reschedule, publish=True)),
                      ("Set covers as thumbnails", lambda: self.task(self._yt_thumbs)))
        self._note(f, "Every upload is Private until its scheduled day, made for kids, Film & Animation, English, "
                      "with the 'altered or synthetic content' label on. Uploading costs 1,600 of the 10,000 daily "
                      "API quota points, so about 6 uploads a day. Until Google approves your API project (audit form "
                      "in the guide), videos uploaded through the API stay private even after their date: in that case "
                      "upload in YouTube Studio and use 'Find selected on my channel' + 'Reschedule selected'.")
        return f

    def _tab_meta(self, nb):
        f = ttk.Frame(nb, padding=8)
        self._row(f, "Facebook Page ID", "meta_page_id", 30)
        self._row(f, "Page access token", "meta_page_token", 60, show="*")
        row = self._row(f, "Instagram account ID", "meta_ig_user_id", 30)
        ttk.Button(row, text="Find from Page", command=lambda: self.task(self._meta_find)).pack(side="left", padx=4)
        self._row(f, "Graph API version", "meta_graph_version", 10)
        self.do_ig = tk.BooleanVar(value=True)
        self.do_fb = tk.BooleanVar(value=True)
        cb = ttk.Frame(f)
        cb.pack(fill="x", pady=4)
        ttk.Checkbutton(cb, text="Instagram Reel", variable=self.do_ig).pack(side="left")
        ttk.Checkbutton(cb, text="Facebook Page Reel", variable=self.do_fb).pack(side="left", padx=12)
        self._buttons(f, ("Publish selected now", lambda: self.task(self._meta_publish, publish=True, scheduled=False)),
                      ("Schedule selected, one a day", lambda: self.task(self._meta_publish, publish=True, scheduled=True)))
        self._note(f, "Facebook schedules natively. Instagram's API can't schedule, so Instagram items go to the "
                      "Queue tab and are posted by this app when their time comes (keep it open, or open it later "
                      "and it catches up). Captions are built from upload-info.txt with Instagram/Facebook hashtags "
                      "and keep the 'Made with AI' line.")
        return f

    def _tab_tiktok(self, nb):
        f = ttk.Frame(nb, padding=8)
        self._row(f, "Client key", "tiktok_client_key", 40)
        self._row(f, "Client secret", "tiktok_client_secret", 40, show="*")
        row = self._row(f, "Redirect port", "tiktok_port", 8)
        ttk.Label(row, text="redirect URI to register: http://localhost:<port>/callback/", foreground="#666").pack(side="left", padx=6)
        m = ttk.Frame(f)
        m.pack(fill="x", pady=4)
        ttk.Label(m, text="Mode", width=22).pack(side="left")
        ttk.Radiobutton(m, text="Send to TikTok drafts (finish in the app)", value="drafts",
                        variable=self.var("tiktok_mode")).pack(side="left")
        ttk.Radiobutton(m, text="Post directly", value="direct", variable=self.var("tiktok_mode")).pack(side="left", padx=12)
        p = ttk.Frame(f)
        p.pack(fill="x", pady=2)
        ttk.Label(p, text="Who can see (direct)", width=22).pack(side="left")
        self.tt_privacy = ttk.Combobox(p, values=["SELF_ONLY"], state="readonly", width=28)
        self.tt_privacy.set("SELF_ONLY")
        self.tt_privacy.pack(side="left")
        self.tt_who = ttk.Label(p, text="", foreground="#666")
        self.tt_who.pack(side="left", padx=8)
        self._buttons(f, ("Sign in", lambda: self.task(self._tt_signin)),
                      ("Sign out", self._tt_signout),
                      ("Refresh account info", lambda: self.task(self._tt_info)))
        self._buttons(f, ("Send selected now", lambda: self.task(self._tt_send, publish=True, scheduled=False)),
                      ("Queue selected, one a day", lambda: self.task(self._tt_send, publish=True, scheduled=True)))
        self._note(f, "Until TikTok audits your app, direct posts can only be 'SELF_ONLY' (private). Drafts mode "
                      "works around that: the video lands in your TikTok inbox and you tap Post in the TikTok app. "
                      "Direct posts are marked as AI-generated content. TikTok has no scheduling API, so queued "
                      "items are sent by this app when their time comes.")
        return f

    def _tab_packs(self, nb):
        f = ttk.Frame(nb, padding=8)
        self._buttons(f, ("Export packs for selected", lambda: self.task(self._packs, sel=True)),
                      ("Export packs for all", lambda: self.task(self._packs, sel=False)),
                      ("Open packs folder", self._open_packs))
        self._note(f, "Writes _social-packs\\instagram, \\tiktok and \\facebook inside the episode folder: each "
                      "video with its cover and a ready caption.txt (story line, 'Made with AI' line, hashtags). "
                      "Use these to post by hand on any platform, with no account setup at all.")
        self.caption_box = tk.Text(f, wrap="word", font=("Consolas", 9), height=10)
        self.caption_box.pack(fill="both", expand=True, pady=6)
        return f

    def _tab_queue(self, nb):
        f = ttk.Frame(nb, padding=8)
        self.queue_tree = ttk.Treeview(f, columns=("platform", "due"), height=8)
        self.queue_tree.heading("#0", text="Folder")
        self.queue_tree.column("#0", width=380)
        self.queue_tree.heading("platform", text="Platform")
        self.queue_tree.heading("due", text="Due")
        self.queue_tree.pack(fill="both", expand=True)
        self._buttons(f, ("Remove selected from queue", self._queue_remove),
                      ("Run due items now", lambda: self.task(self._queue_due, publish=True)))
        return f

    # ---------- plumbing ----------
    def log(self, text):
        self.msgs.put(("log", text))

    def _pump(self):
        try:
            while True:
                kind, val = self.msgs.get_nowait()
                if kind == "log":
                    self.log_box.insert("end", f"{datetime.now():%H:%M:%S}  {val}\n")
                    self.log_box.see("end")
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def ui(self, fn):
        self.msgs.put(("call", fn))

    def save(self):
        for k, v in self.vars.items():
            self.cfg[k] = v.get().strip()
        core.save_config(self.cfg)

    def task(self, fn, publish=False, **kw):
        if self.busy:
            messagebox.showinfo("Busy", "Wait for the current job to finish (see the log).")
            return
        if publish and not self.license_ok:
            if not messagebox.askyesno("Before publishing", LICENSE_NOTE):
                return
            self.license_ok = True
        self.save()
        # Tk widgets must only be read on the main thread, so the worker gets a snapshot.
        self.snap = {"sel": set(self.tree.selection()), "privacy": self.tt_privacy.get(),
                     "ig": self.do_ig.get(), "fb": self.do_fb.get()}
        self.busy = True

        def run():
            try:
                fn(**kw)
            except Exception as e:
                self.log(f"ERROR: {e}")
                with open(core.APP_DIR / "error.log", "a", encoding="utf-8") as fh:
                    fh.write(traceback.format_exc() + "\n")
            finally:
                self.busy = False
                self.ui(self.refresh)
        threading.Thread(target=run, daemon=True).start()

    def selected(self, required=True, live=False):
        names = set(self.tree.selection()) if live else self.snap["sel"]
        chosen = [it for it in self.items if it.name in names]
        if required and not chosen:
            raise RuntimeError("Select one or more rows first")
        return chosen

    def slots(self, items):
        times = core.schedule(len(items), self.cfg["start_date"], self.cfg["time"], self.cfg["utc_offset"])
        if times and times[0] < datetime.now(times[0].tzinfo) + timedelta(minutes=20):
            raise RuntimeError("The first slot is less than 20 minutes away; pick a later start date or time")
        return times

    def mark(self, item, platform, value):
        self.state_["videos"].setdefault(item.name, {})[platform] = value
        core.save_state(self.state_)

    def status(self, item, platform):
        return self.state_["videos"].get(item.name, {}).get(platform)

    # ---------- folder ----------
    def _pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.var("folder").get() or "D:\\")
        if d:
            self.var("folder").set(os.path.normpath(d))
            self.reload()

    def reload(self):
        self.save()
        self.items = core.load_folder(self.cfg["folder"])
        self.refresh()
        self.log(f"{len(self.items)} videos in {self.cfg['folder']}" if self.items else
                 "No numbered folders with video.mp4 + upload-info.txt found in that folder")

    def refresh(self):
        keep = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for it in self.items:
            title_score, hook, _ = core.lint(it)
            vals = [it.title, f"{title_score}/{hook}"]
            for p in PLATFORMS:
                s = self.status(it, p) or {}
                vals.append(s.get("label", "") if isinstance(s, dict) else "")
            self.tree.insert("", "end", iid=it.name, text=it.name, values=vals)
        sel = [n for n in keep if self.tree.exists(n)]
        if sel:
            self.tree.selection_set(sel)
        self.queue_tree.delete(*self.queue_tree.get_children())
        for i, q in enumerate(self.state_["queue"]):
            self.queue_tree.insert("", "end", iid=str(i), text=q["folder"], values=(q["platform"], q["due"][:16].replace("T", " ")))

    def _show_lint(self):
        chosen = self.selected(required=False, live=True)
        self.lint_box.delete("1.0", "end")
        self.caption_box.delete("1.0", "end")
        for it in chosen:
            self.lint_box.insert("end", f"{it.name}\n{core.lint(it)[2]}\n\n")
        if chosen:
            self.caption_box.insert("end", "Instagram caption preview:\n\n" + core.social_caption(chosen[0], "instagram"))

    # ---------- YouTube ----------
    def _pick_secret(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if p:
            self.var("yt_client_secret").set(os.path.normpath(p))
            self.save()

    def _yt(self):
        return youtube.client(self.cfg["yt_client_secret"])

    def _yt_signin(self):
        yt = self._yt()
        ch = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
        self.log(f"YouTube: signed in as {ch['snippet']['title']}")
        if "glowgills" not in ch["snippet"]["title"].lower():
            self.log("  WARNING: this is not The Glowgills channel. Press 'Sign out', then 'Sign in' again "
                     "and pick The Glowgills in Google's channel list.")

    def _yt_signout(self):
        youtube.sign_out()
        self.log("YouTube: signed out")

    def _yt_stats(self):
        self.log("YouTube stats:\n" + youtube.stats(self._yt()))

    def _yt_upload(self):
        items = self.selected()
        todo = [it for it in items if not (self.status(it, "youtube") or {}).get("id")]
        for it in items:
            if it not in todo:
                self.log(f"skip {it.name}: already on YouTube")
        yt = self._yt()
        for it, when in zip(todo, self.slots(todo)):
            self.log(f"YouTube: uploading {it.name} (goes live {when:%Y-%m-%d %H:%M})")
            vid = youtube.upload(yt, it, when, "private", self.log)
            self.mark(it, "youtube", {"id": vid, "label": f"{when:%m-%d %H:%M}"})
            self.log(f"  done: https://youtu.be/{vid}")
            if it.cover:
                try:
                    youtube.set_thumbnail(yt, vid, it.cover)
                    self.log("  cover set as thumbnail")
                except Exception as e:
                    self.log(f"  thumbnail not set: {e}")

    def _yt_link(self):
        items = self.selected()
        found = youtube.match_existing(self._yt(), items)
        for it in items:
            vid = found.get(it.name)
            if vid:
                old = self.status(it, "youtube") or {}
                self.mark(it, "youtube", {"id": vid, "label": old.get("label") or "on channel"})
                self.log(f"found {it.name}: https://youtu.be/{vid}")
            else:
                self.log(f"not found on the channel (title differs?): {it.name}")

    def _yt_reschedule(self):
        items = [it for it in self.selected() if (self.status(it, "youtube") or {}).get("id")]
        if not items:
            raise RuntimeError("None of the selected rows are linked to a YouTube video yet")
        yt = self._yt()
        for it, when in zip(items, self.slots(items)):
            vid = self.status(it, "youtube")["id"]
            if youtube.reschedule(yt, vid, when):
                self.mark(it, "youtube", {"id": vid, "label": f"{when:%m-%d %H:%M}"})
                self.log(f"{it.name}: goes live {when:%Y-%m-%d %H:%M}")
            else:
                self.mark(it, "youtube", {"id": vid, "label": "public"})
                self.log(f"{it.name}: already public, left alone")

    def _yt_thumbs(self):
        yt = self._yt()
        for it in self.selected():
            vid = (self.status(it, "youtube") or {}).get("id")
            if vid and it.cover:
                youtube.set_thumbnail(yt, vid, it.cover)
                self.log(f"{it.name}: thumbnail set")
            else:
                self.log(f"{it.name}: skipped ({'no cover.jpg' if vid else 'not linked to a YouTube video'})")

    # ---------- Instagram + Facebook ----------
    def _meta_args(self):
        c = self.cfg
        if not (c["meta_page_id"] and c["meta_page_token"]):
            raise RuntimeError("Enter the Facebook Page ID and Page access token first")
        return c["meta_graph_version"] or "v23.0", c["meta_page_id"], c["meta_page_token"]

    def _meta_find(self):
        ver, page, tok = self._meta_args()
        name, ig_id, user = meta.find_accounts(ver, page, tok)
        self.log(f"Page: {name}")
        if ig_id:
            self.ui(lambda: self.var("meta_ig_user_id").set(ig_id))
            self.log(f"Instagram: @{user} (id {ig_id})")
        else:
            self.log("No Instagram professional account is connected to this Page yet")

    def _meta_publish(self, scheduled):
        items = self.selected()
        ver, page, tok = self._meta_args()
        times = self.slots(items) if scheduled else [None] * len(items)
        for it, when in zip(items, times):
            if self.snap["fb"] and not self.status(it, "facebook"):
                self.log(f"Facebook: {it.name}")
                vid = meta.facebook_reel(ver, page, tok, it.video, core.social_caption(it, "facebook"), when)
                self.mark(it, "facebook", {"id": vid, "label": f"{when:%m-%d %H:%M}" if when else "posted"})
                self.log("  done")
            if self.snap["ig"] and not self.status(it, "instagram"):
                if when:
                    self.enqueue(it, "instagram", when)
                else:
                    self._ig_now(it)

    def _ig_now(self, it):
        ver, _, tok = self._meta_args()
        ig = self.cfg["meta_ig_user_id"]
        if not ig:
            raise RuntimeError("Enter the Instagram account ID (or press 'Find from Page')")
        self.log(f"Instagram: {it.name}")
        mid = meta.instagram_reel(ver, ig, tok, it.video, core.social_caption(it, "instagram"), self.log)
        self.mark(it, "instagram", {"id": mid, "label": "posted"})
        self.log("  done")

    # ---------- TikTok ----------
    def _tt_token(self):
        return tiktok.access_token(self.cfg["tiktok_client_key"], self.cfg["tiktok_client_secret"])

    def _tt_signin(self):
        tiktok.sign_in(self.cfg["tiktok_client_key"], self.cfg["tiktok_client_secret"], self.cfg["tiktok_port"], self.log)
        self.log("TikTok: signed in")
        self._tt_info()

    def _tt_signout(self):
        tiktok.sign_out()
        self.log("TikTok: signed out")

    def _tt_info(self):
        info = tiktok.creator_info(self._tt_token())
        opts = info.get("privacy_level_options") or ["SELF_ONLY"]
        who = f"@{info.get('creator_username', '?')} ({info.get('creator_nickname', '')}), max {info.get('max_video_post_duration_sec', '?')} s"

        def apply():
            self.tt_privacy.configure(values=opts)
            if self.tt_privacy.get() not in opts:
                self.tt_privacy.set(opts[0])
            self.tt_who.configure(text=who)
        self.ui(apply)
        self.log(f"TikTok: {who}; can post as {', '.join(opts)}")

    def _tt_send(self, scheduled):
        items = [it for it in self.selected() if not self.status(it, "tiktok")]
        if scheduled:
            for it, when in zip(items, self.slots(items)):
                self.enqueue(it, "tiktok", when)
            return
        for it in items:
            self._tt_now(it)

    def _tt_now(self, it):
        mode = self.cfg["tiktok_mode"]
        self.log(f"TikTok ({mode}): {it.name}")
        pid, st = tiktok.post(self._tt_token(), it.video, core.social_caption(it, "tiktok"), mode, self.snap["privacy"], self.log)
        self.mark(it, "tiktok", {"id": pid, "label": "in drafts" if st == "SEND_TO_USER_INBOX" else "posted"})
        self.log(f"  {st}" + (" - open TikTok and finish the post from your inbox" if mode == "drafts" else ""))

    # ---------- queue ----------
    def enqueue(self, it, platform, when):
        self.state_["queue"].append({"folder": it.name, "platform": platform, "due": when.isoformat()})
        self.mark(it, platform, {"label": f"queued {when:%m-%d %H:%M}", "queued": True})
        self.log(f"{platform}: {it.name} queued for {when:%Y-%m-%d %H:%M}")

    def _queue_remove(self):
        drop = {int(i) for i in self.queue_tree.selection()}
        for i in sorted(drop, reverse=True):
            q = self.state_["queue"].pop(i)
            v = self.state_["videos"].get(q["folder"], {})
            if (v.get(q["platform"]) or {}).get("queued"):
                v.pop(q["platform"], None)
        core.save_state(self.state_)
        self.refresh()

    def _queue_due(self):
        now = datetime.now().astimezone()
        by_name = {it.name: it for it in self.items}
        for q in list(self.state_["queue"]):
            if datetime.fromisoformat(q["due"]) > now:
                continue
            it = by_name.get(q["folder"])
            if not it:
                self.log(f"queue: {q['folder']} is no longer in the episode folder, skipped")
                continue
            self.state_["videos"].get(it.name, {}).pop(q["platform"], None)
            try:
                (self._ig_now if q["platform"] == "instagram" else self._tt_now)(it)
            except Exception:
                self.mark(it, q["platform"], {"label": "queued (error)", "queued": True})
                raise
            self.state_["queue"].remove(q)
            core.save_state(self.state_)

    def _run_queue(self):
        due = any(datetime.fromisoformat(q["due"]) <= datetime.now().astimezone() for q in self.state_["queue"])
        if due and not self.busy and self.license_ok:
            self.task(self._queue_due)
        elif due and not self.license_ok and not self.queue_hint_shown:
            self.queue_hint_shown = True
            self.log("Queue has due items: press 'Run due items now' in the Queue tab to post them")
        self.after(60_000, self._run_queue)

    # ---------- packs ----------
    def _packs(self, sel):
        items = self.selected() if sel else self.items
        out = core.export_packs(items, self.cfg["folder"], self.log)
        self.log(f"Packs ready in {out}")

    def _open_packs(self):
        p = Path(self.cfg["folder"]) / "_social-packs"
        if p.exists():
            os.startfile(p)
        else:
            self.log("No packs yet: export them first")


if __name__ == "__main__":
    App().mainloop()
