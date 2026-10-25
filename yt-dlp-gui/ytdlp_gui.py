#!/usr/bin/env python3
"""Ultimate Video Downloader — a Tkinter GUI for yt-dlp.

Features: download queue, video/audio presets, resolution cap, playlists,
subtitles, thumbnail/metadata/chapter embedding, SponsorBlock, browser
cookies, rate limiting, proxy, format inspector, live progress and a log.

Run:  python ytdlp_gui.py      (requires: pip install yt-dlp; ffmpeg on PATH
                                for merging, audio conversion and embedding)
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

APP_NAME = "Ultimate Video Downloader"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".ytdlp_gui.json")

PRESETS = [
    "Best video + audio",
    "MP4 (H.264/AAC, max compatibility)",
    "WebM (VP9/Opus)",
    "Video only (no audio)",
    "Audio: MP3",
    "Audio: M4A",
    "Audio: Opus",
    "Audio: FLAC",
    "Audio: WAV",
    "Audio: best original",
]
RESOLUTIONS = ["Any", "2160", "1440", "1080", "720", "480", "360", "240"]
BROWSERS = ["None", "chrome", "firefox", "edge", "brave", "opera", "vivaldi", "chromium", "safari"]
SPONSORBLOCK = ["Off", "Mark as chapters", "Remove sponsors", "Remove all segments"]
DEFAULT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"

DEFAULTS = {
    "output_dir": os.path.join(os.path.expanduser("~"), "Downloads"),
    "template": DEFAULT_TEMPLATE,
    "preset": PRESETS[0],
    "resolution": "Any",
    "playlist": False,
    "playlist_items": "",
    "subtitles": False,
    "auto_subs": False,
    "sub_langs": "en.*",
    "embed_subs": True,
    "embed_thumbnail": True,
    "embed_metadata": True,
    "embed_chapters": True,
    "sponsorblock": "Off",
    "cookies_browser": "None",
    "cookies_file": "",
    "rate_limit": "",
    "proxy": "",
    "fragments": 4,
    "parallel": 2,
    "archive": False,
    "restrict_names": False,
    "keep_original": False,
}


def _has_ffmpeg():
    return shutil.which("ffmpeg") is not None


def _parse_rate(text):
    """'2M' -> 2097152, '500K' -> 512000, '' -> None."""
    text = (text or "").strip().upper().rstrip("B/S").rstrip("I")
    if not text:
        return None
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    if text[-1] in mult:
        return int(float(text[:-1]) * mult[text[-1]])
    return int(float(text))


def build_ydl_opts(s):
    """Translate GUI settings (dict) into a yt-dlp options dict."""
    preset, res = s["preset"], s["resolution"]
    h = "" if res == "Any" else f"[height<={res}]"
    opts = {
        "outtmpl": os.path.join(s["output_dir"], s["template"] or DEFAULT_TEMPLATE),
        "noplaylist": not s["playlist"],
        "concurrent_fragment_downloads": int(s["fragments"] or 1),
        "restrictfilenames": bool(s["restrict_names"]),
        "keepvideo": bool(s["keep_original"]),
        "ignoreerrors": "only_download" if s["playlist"] else False,
        "retries": 10,
        "fragment_retries": 10,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
    }
    pps = []
    audio_only = preset.startswith("Audio")

    if preset == "__custom__" and s.get("custom_format"):
        opts["format"] = s["custom_format"]
    elif preset == "Best video + audio":
        opts["format"] = f"bv*{h}+ba/b{h}/b"
    elif preset.startswith("MP4"):
        opts["format"] = (f"bv*[vcodec^=avc]{h}+ba[ext=m4a]/b[ext=mp4]{h}/bv*{h}+ba/b")
        opts["merge_output_format"] = "mp4"
        pps.append({"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"})
    elif preset.startswith("WebM"):
        opts["format"] = f"bv*[ext=webm]{h}+ba[ext=webm]/bv*{h}+ba/b"
        opts["merge_output_format"] = "webm"
    elif preset.startswith("Video only"):
        opts["format"] = f"bv*{h}/b{h}/b"
    elif audio_only:
        opts["format"] = "ba/b"
        codec = preset.split(":", 1)[1].strip().lower()
        if codec != "best original":
            pps.append({"key": "FFmpegExtractAudio", "preferredcodec": codec,
                        "preferredquality": "0"})

    if s["playlist"] and s["playlist_items"].strip():
        opts["playlist_items"] = s["playlist_items"].strip()

    if s["subtitles"] or s["auto_subs"]:
        opts["writesubtitles"] = bool(s["subtitles"])
        opts["writeautomaticsub"] = bool(s["auto_subs"])
        opts["subtitleslangs"] = [x.strip() for x in s["sub_langs"].split(",") if x.strip()]
        if s["embed_subs"] and not audio_only:
            pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})

    sb = s["sponsorblock"]
    if sb != "Off":
        cats = ["sponsor"] if sb == "Remove sponsors" else ["all"]
        pps.append({"key": "SponsorBlock", "categories": ["all"], "when": "after_filter"})
        if sb.startswith("Remove"):
            pps.append({"key": "ModifyChapters", "remove_sponsor_segments": cats,
                        "remove_chapters_patterns": [], "remove_ranges": []})

    if s["embed_metadata"] or s["embed_chapters"] or sb == "Mark as chapters":
        pps.append({"key": "FFmpegMetadata", "add_metadata": bool(s["embed_metadata"]),
                    "add_chapters": bool(s["embed_chapters"]) or sb == "Mark as chapters"})
    if s["embed_thumbnail"]:
        opts["writethumbnail"] = True
        pps.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
        pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

    if s["cookies_file"].strip():
        opts["cookiefile"] = s["cookies_file"].strip()
    elif s["cookies_browser"] != "None":
        opts["cookiesfrombrowser"] = (s["cookies_browser"],)
    rate = _parse_rate(s["rate_limit"])
    if rate:
        opts["ratelimit"] = rate
    if s["proxy"].strip():
        opts["proxy"] = s["proxy"].strip()
    if s["archive"]:
        opts["download_archive"] = os.path.join(s["output_dir"], ".ytdlp-archive.txt")

    if pps:
        opts["postprocessors"] = pps
    return opts


def _fmt_bytes(n):
    if not n:
        return "?"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def _fmt_eta(sec):
    if sec is None:
        return "--:--"
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


class Cancelled(Exception):
    pass


@dataclass
class Job:
    jid: int
    url: str
    settings: dict
    title: str = ""
    status: str = "Queued"
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)


class QueueLogger:
    def __init__(self, post, jid):
        self.post, self.jid = post, jid

    def debug(self, msg):
        if not msg.startswith("[debug]"):
            self.post("log", self.jid, msg)

    def info(self, msg):
        self.post("log", self.jid, msg)

    def warning(self, msg):
        self.post("log", self.jid, "WARNING: " + msg)

    def error(self, msg):
        self.post("log", self.jid, msg)


def run_job(job, post):
    """Worker-thread body: download one URL, reporting through post()."""
    import yt_dlp

    def hook(d):
        if job.cancel.is_set():
            raise Cancelled()
        info = d.get("info_dict") or {}
        if info.get("title") and not job.title:
            post("title", job.jid, info["title"])
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            pct = done / total * 100 if total else 0.0
            post("progress", job.jid, {
                "percent": pct,
                "speed": _fmt_bytes(d.get("speed")) + "/s" if d.get("speed") else "",
                "eta": _fmt_eta(d.get("eta")),
                "size": _fmt_bytes(total),
                "status": "Downloading",
            })
        elif d["status"] == "finished":
            post("progress", job.jid, {"percent": 100.0, "status": "Processing", "eta": ""})

    def pp_hook(d):
        if job.cancel.is_set():
            raise Cancelled()
        if d["status"] == "started":
            post("progress", job.jid, {"status": f"Post: {d.get('postprocessor', '')}"})

    opts = build_ydl_opts(job.settings)
    opts["logger"] = QueueLogger(post, job.jid)
    opts["progress_hooks"] = [hook]
    opts["postprocessor_hooks"] = [pp_hook]
    try:
        os.makedirs(job.settings["output_dir"], exist_ok=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            code = ydl.download([job.url])
        post("done", job.jid, "Done" if code == 0 else "Finished with errors")
    except Cancelled:
        post("done", job.jid, "Cancelled")
    except Exception as e:  # yt_dlp.utils.DownloadError and anything unexpected
        if job.cancel.is_set():
            post("done", job.jid, "Cancelled")
        else:
            post("log", job.jid, f"ERROR: {e}")
            post("done", job.jid, "Failed")


FROZEN = getattr(sys, "frozen", False)
RELEASES_URL = "https://github.com/stepanalefan/11/releases/latest"


def _prepare_frozen():
    """Fixes for the PyInstaller .exe: no console streams, bundled ffmpeg."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:  # --noconsole builds have no std streams
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    bundle = getattr(sys, "_MEIPASS", None)
    exe_dir = os.path.dirname(sys.executable)
    for d in (bundle, exe_dir):  # bundled ffmpeg first, then one placed next to the exe
        if d and os.path.isfile(os.path.join(d, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            break


def selftest():
    """Non-GUI sanity check used by the build pipeline. Exit code 0 = OK."""
    import tkinter  # noqa: F401
    import yt_dlp
    from yt_dlp.extractor import gen_extractor_classes
    assert len(list(gen_extractor_classes())) > 1000, "extractors missing from bundle"
    for p in PRESETS:
        yt_dlp.YoutubeDL(build_ydl_opts(dict(DEFAULTS, preset=p, subtitles=True,
                                             sponsorblock="Remove sponsors")))
    assert _has_ffmpeg(), "ffmpeg not found"
    print("selftest ok:", yt_dlp.version.__version__)


def main():
    if FROZEN:
        _prepare_frozen()
    if "--selftest" in sys.argv:
        try:
            selftest()
        except Exception as e:
            print("selftest FAILED:", repr(e))
            sys.exit(1)
        sys.exit(0)
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        sys.exit("Tkinter is not available. Install it (e.g. 'sudo apt install python3-tk').")
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        root = tk.Tk()
        root.withdraw()
        if not FROZEN and messagebox.askyesno(APP_NAME, "yt-dlp is not installed. Install it now with pip?"):
            subprocess.call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"])
            os.execv(sys.executable, [sys.executable] + sys.argv)
        sys.exit(1)

    App(tk, ttk, filedialog, messagebox).run()


class App:
    def __init__(self, tk, ttk, filedialog, messagebox):
        self.tk, self.ttk, self.fd, self.mb = tk, ttk, filedialog, messagebox
        self.events = queue.Queue()
        self.jobs = {}
        self.next_id = 1
        self.active = 0
        self.lock = threading.Lock()

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1040x720")
        self.root.minsize(860, 600)
        try:
            ttk.Style().theme_use("clam")
        except tk.TclError:
            pass

        self.cfg = dict(DEFAULTS)
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                self.cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
        self.vars = {}
        for k, v in self.cfg.items():
            cls = tk.BooleanVar if isinstance(v, bool) else tk.IntVar if isinstance(v, int) else tk.StringVar
            self.vars[k] = cls(value=v)

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.pump)
        if not _has_ffmpeg():
            self.log("WARNING: ffmpeg not found on PATH — merging, audio conversion and "
                     "embedding will not work. Get it from https://ffmpeg.org/download.html")

    # ---------- layout ----------
    def _build(self):
        tk, ttk, v = self.tk, self.ttk, self.vars
        pad = {"padx": 6, "pady": 3}
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="URLs (one per line — videos, playlists, channels):").grid(row=0, column=0, sticky="w")
        self.url_box = tk.Text(top, height=4, wrap="none", undo=True)
        self.url_box.grid(row=1, column=0, columnspan=4, sticky="nsew")
        btns = ttk.Frame(top)
        btns.grid(row=1, column=4, sticky="ns", padx=(6, 0))
        ttk.Button(btns, text="Paste", command=self.paste).pack(fill="x")
        ttk.Button(btns, text="Clear", command=lambda: self.url_box.delete("1.0", "end")).pack(fill="x", pady=2)
        ttk.Button(btns, text="Formats…", command=self.show_formats).pack(fill="x")
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text="Save to:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        out = ttk.Frame(top)
        out.grid(row=3, column=0, columnspan=5, sticky="ew")
        ttk.Entry(out, textvariable=v["output_dir"]).pack(side="left", fill="x", expand=True)
        ttk.Button(out, text="Browse…", command=self.browse_dir).pack(side="left", padx=4)
        ttk.Button(out, text="Open", command=lambda: self.open_path(v["output_dir"].get())).pack(side="left")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="x", padx=8)

        # Format tab
        f1 = ttk.Frame(nb, padding=8)
        nb.add(f1, text="Format")
        ttk.Label(f1, text="Preset:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Combobox(f1, textvariable=v["preset"], values=PRESETS, state="readonly", width=34).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(f1, text="Max resolution:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Combobox(f1, textvariable=v["resolution"], values=RESOLUTIONS, state="readonly", width=8).grid(row=0, column=3, sticky="w", **pad)
        ttk.Label(f1, text="Filename template:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(f1, textvariable=v["template"], width=50).grid(row=1, column=1, columnspan=3, sticky="ew", **pad)
        ttk.Checkbutton(f1, text="Download whole playlist", variable=v["playlist"]).grid(row=2, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(f1, text="Items (e.g. 1-5,8):").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(f1, textvariable=v["playlist_items"], width=12).grid(row=2, column=3, sticky="w", **pad)
        ttk.Checkbutton(f1, text="Keep original file after conversion", variable=v["keep_original"]).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(f1, text="ASCII-safe filenames", variable=v["restrict_names"]).grid(row=3, column=2, columnspan=2, sticky="w", **pad)

        # Extras tab
        f2 = ttk.Frame(nb, padding=8)
        nb.add(f2, text="Subtitles & Extras")
        ttk.Checkbutton(f2, text="Subtitles", variable=v["subtitles"]).grid(row=0, column=0, sticky="w", **pad)
        ttk.Checkbutton(f2, text="Auto-generated subtitles", variable=v["auto_subs"]).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(f2, text="Languages:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(f2, textvariable=v["sub_langs"], width=14).grid(row=0, column=3, sticky="w", **pad)
        ttk.Checkbutton(f2, text="Embed subtitles", variable=v["embed_subs"]).grid(row=0, column=4, sticky="w", **pad)
        ttk.Checkbutton(f2, text="Embed thumbnail", variable=v["embed_thumbnail"]).grid(row=1, column=0, sticky="w", **pad)
        ttk.Checkbutton(f2, text="Embed metadata", variable=v["embed_metadata"]).grid(row=1, column=1, sticky="w", **pad)
        ttk.Checkbutton(f2, text="Embed chapters", variable=v["embed_chapters"]).grid(row=1, column=2, sticky="w", **pad)
        ttk.Label(f2, text="SponsorBlock:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Combobox(f2, textvariable=v["sponsorblock"], values=SPONSORBLOCK, state="readonly", width=22).grid(row=2, column=1, columnspan=2, sticky="w", **pad)

        # Network tab
        f3 = ttk.Frame(nb, padding=8)
        nb.add(f3, text="Network & Auth")
        ttk.Label(f3, text="Cookies from browser:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Combobox(f3, textvariable=v["cookies_browser"], values=BROWSERS, state="readonly", width=12).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(f3, text="or cookies.txt:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(f3, textvariable=v["cookies_file"], width=30).grid(row=0, column=3, sticky="w", **pad)
        ttk.Button(f3, text="…", width=3, command=self.browse_cookies).grid(row=0, column=4, sticky="w")
        ttk.Label(f3, text="Rate limit (e.g. 2M):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(f3, textvariable=v["rate_limit"], width=10).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(f3, text="Proxy:").grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(f3, textvariable=v["proxy"], width=30).grid(row=1, column=3, sticky="w", **pad)
        ttk.Label(f3, text="Fragments per file:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Spinbox(f3, from_=1, to=16, textvariable=v["fragments"], width=5).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(f3, text="Parallel downloads:").grid(row=2, column=2, sticky="w", **pad)
        ttk.Spinbox(f3, from_=1, to=8, textvariable=v["parallel"], width=5).grid(row=2, column=3, sticky="w", **pad)
        ttk.Checkbutton(f3, text="Skip already-downloaded (archive file)", variable=v["archive"]).grid(row=3, column=0, columnspan=3, sticky="w", **pad)

        # Action bar
        bar = ttk.Frame(self.root, padding=(8, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="⬇  Download", command=self.enqueue).pack(side="left")
        ttk.Button(bar, text="Cancel selected", command=self.cancel_selected).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel all", command=self.cancel_all).pack(side="left")
        ttk.Button(bar, text="Retry failed", command=self.retry_failed).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear finished", command=self.clear_finished).pack(side="left")
        ttk.Button(bar, text="Update yt-dlp", command=self.update_ytdlp).pack(side="right")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(bar, textvariable=self.status).pack(side="right", padx=10)

        # Queue + log
        pane = ttk.PanedWindow(self.root, orient="vertical")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        qf = ttk.Frame(pane)
        cols = ("title", "status", "progress", "size", "speed", "eta")
        self.tree = ttk.Treeview(qf, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, (420, 130, 80, 90, 100, 70)):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w, anchor="w" if c == "title" else "center", stretch=(c == "title"))
        sb = ttk.Scrollbar(qf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.open_path(self.vars["output_dir"].get()))
        pane.add(qf, weight=3)

        lf = ttk.Frame(pane)
        self.log_box = tk.Text(lf, height=8, state="disabled", wrap="word")
        lsb = ttk.Scrollbar(lf, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=lsb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        pane.add(lf, weight=1)

        self.root.bind("<Control-Return>", lambda e: self.enqueue())

    # ---------- helpers ----------
    def settings(self):
        out = {}
        for k, var in self.vars.items():
            try:
                out[k] = var.get()
            except self.tk.TclError:
                out[k] = DEFAULTS[k]
        return out

    def save_cfg(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.settings(), f, indent=2)
        except OSError:
            pass

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def post(self, kind, jid, data):
        self.events.put((kind, jid, data))

    def paste(self):
        try:
            text = self.root.clipboard_get()
        except self.tk.TclError:
            return
        cur = self.url_box.get("1.0", "end").strip()
        self.url_box.insert("end", ("\n" if cur else "") + text.strip())

    def browse_dir(self):
        d = self.fd.askdirectory(initialdir=self.vars["output_dir"].get() or os.path.expanduser("~"))
        if d:
            self.vars["output_dir"].set(d)

    def browse_cookies(self):
        f = self.fd.askopenfilename(filetypes=[("Cookies", "*.txt"), ("All files", "*")])
        if f:
            self.vars["cookies_file"].set(f)

    def open_path(self, path):
        if not os.path.isdir(path):
            return
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def urls(self):
        lines = self.url_box.get("1.0", "end").splitlines()
        seen, out = set(), []
        for ln in lines:
            ln = ln.strip()
            if ln and not ln.startswith("#") and ln not in seen:
                seen.add(ln)
                out.append(ln)
        return out

    # ---------- queue ----------
    def enqueue(self):
        urls = self.urls()
        if not urls:
            self.mb.showinfo(APP_NAME, "Paste one or more URLs first.")
            return
        s = self.settings()
        if not s["output_dir"]:
            self.mb.showerror(APP_NAME, "Choose an output folder.")
            return
        self.save_cfg()
        for url in urls:
            self._add_job(url, dict(s))
        self.url_box.delete("1.0", "end")
        self.schedule()

    def _add_job(self, url, s):
        job = Job(self.next_id, url, s)
        self.next_id += 1
        self.jobs[job.jid] = job
        self.tree.insert("", "end", iid=str(job.jid), values=(url, "Queued", "0%", "", "", ""))

    def schedule(self):
        limit = max(1, int(self.settings()["parallel"] or 1))
        for job in self.jobs.values():
            if self.active >= limit:
                break
            if job.status == "Queued":
                job.status = "Starting"
                self.active += 1
                self._refresh(job)
                threading.Thread(target=run_job, args=(job, self.post), daemon=True).start()
        self._update_status()

    def _refresh(self, job):
        if self.tree.exists(str(job.jid)):
            self.tree.item(str(job.jid), values=(job.title or job.url, job.status,
                                                 f"{job.percent:.1f}%", job.size, job.speed, job.eta))

    def _update_status(self):
        counts = {}
        for j in self.jobs.values():
            counts[j.status] = counts.get(j.status, 0) + 1
        queued = counts.get("Queued", 0)
        done = counts.get("Done", 0)
        self.status.set(f"Active: {self.active}   Queued: {queued}   Done: {done}   Total: {len(self.jobs)}")

    def pump(self):
        try:
            while True:
                kind, jid, data = self.events.get_nowait()
                job = self.jobs.get(jid)
                if kind == "log":
                    self.log(f"#{jid} {data}" if jid else data)
                    continue
                if job is None:
                    continue
                if kind == "title":
                    job.title = data
                elif kind == "progress":
                    for k, val in data.items():
                        setattr(job, k, val)
                elif kind == "done":
                    job.status, job.speed, job.eta = data, "", ""
                    if data == "Done":
                        job.percent = 100.0
                    self.active = max(0, self.active - 1)
                    self.log(f"#{jid} {data}: {job.title or job.url}")
                    self.schedule()
                self._refresh(job)
                self._update_status()
        except queue.Empty:
            pass
        self.root.after(150, self.pump)

    def _selected_jobs(self):
        return [self.jobs[int(i)] for i in self.tree.selection() if int(i) in self.jobs]

    def _cancel(self, jobs):
        for j in jobs:
            if j.status == "Queued":
                j.status = "Cancelled"
                self._refresh(j)
            elif j.status not in ("Done", "Failed", "Cancelled", "Finished with errors"):
                j.cancel.set()
                j.status = "Cancelling…"
                self._refresh(j)
        self._update_status()

    def cancel_selected(self):
        self._cancel(self._selected_jobs())

    def cancel_all(self):
        self._cancel(list(self.jobs.values()))

    def retry_failed(self):
        for j in list(self.jobs.values()):
            if j.status in ("Failed", "Cancelled", "Finished with errors"):
                self.tree.delete(str(j.jid))
                del self.jobs[j.jid]
                self._add_job(j.url, j.settings)
        self.schedule()

    def clear_finished(self):
        for j in list(self.jobs.values()):
            if j.status in ("Done", "Failed", "Cancelled", "Finished with errors"):
                self.tree.delete(str(j.jid))
                del self.jobs[j.jid]
        self._update_status()

    # ---------- format inspector ----------
    def show_formats(self):
        urls = self.urls()
        if not urls:
            self.mb.showinfo(APP_NAME, "Paste a URL first.")
            return
        url, s = urls[0], self.settings()
        self.log(f"Fetching formats for {url} …")

        def work():
            import yt_dlp
            opts = {"quiet": True, "noplaylist": True, "skip_download": True}
            base = build_ydl_opts(s)
            for k in ("cookiefile", "cookiesfrombrowser", "proxy"):
                if k in base:
                    opts[k] = base[k]
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                self.root.after(0, lambda: self._format_window(url, info))
            except Exception as e:
                self.post("log", 0, f"ERROR fetching formats: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _format_window(self, url, info):
        tk, ttk = self.tk, self.ttk
        if info.get("_type") == "playlist":
            self.mb.showinfo(APP_NAME, f"Playlist: {info.get('title')} ({len(info.get('entries') or [])} items)")
            return
        win = tk.Toplevel(self.root)
        win.title(f"Formats — {info.get('title', url)}")
        win.geometry("900x480")
        dur = info.get("duration")
        ttk.Label(win, padding=6, text=f"{info.get('title')}  •  {info.get('uploader') or ''}  •  "
                                       f"{_fmt_eta(dur) if dur else ''}").pack(anchor="w")
        cols = ("id", "ext", "resolution", "fps", "vcodec", "acodec", "size", "note")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for c, w in zip(cols, (80, 60, 100, 50, 130, 110, 90, 200)):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w")
        for f in reversed(info.get("formats") or []):
            size = f.get("filesize") or f.get("filesize_approx")
            tree.insert("", "end", values=(
                f.get("format_id"), f.get("ext"), f.get("resolution") or "", f.get("fps") or "",
                f.get("vcodec") or "", f.get("acodec") or "", _fmt_bytes(size) if size else "",
                f.get("format_note") or ""))
        tree.pack(fill="both", expand=True, padx=6)

        def download_selected():
            ids = [tree.item(i, "values")[0] for i in tree.selection()]
            if not ids:
                return
            s = self.settings()
            self.save_cfg()
            s["preset"] = "__custom__"
            s["custom_format"] = "+".join(ids)
            self._add_job(url, s)
            win.destroy()
            self.schedule()

        bar = ttk.Frame(win, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="Select one format, or a video + an audio format (Ctrl-click) to merge.").pack(side="left")
        ttk.Button(bar, text="Download selected", command=download_selected).pack(side="right")

    # ---------- misc ----------
    def update_ytdlp(self):
        if FROZEN:  # pip can't update a bundled exe; point to the newest build instead
            import webbrowser
            import yt_dlp
            if self.mb.askyesno(APP_NAME, f"This app bundles yt-dlp {yt_dlp.version.__version__}.\n\n"
                                          "Open the download page for the newest build?"):
                webbrowser.open(RELEASES_URL)
            return
        self.log("Updating yt-dlp …")

        def work():
            p = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                               capture_output=True, text=True)
            tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
            self.post("log", 0, ("yt-dlp updated — restart the app to use the new version. " if p.returncode == 0
                                 else "Update failed: ") + tail[0])

        threading.Thread(target=work, daemon=True).start()

    def on_close(self):
        busy = any(j.status not in ("Queued", "Done", "Failed", "Cancelled", "Finished with errors")
                   for j in self.jobs.values())
        if busy and not self.mb.askyesno(APP_NAME, "Downloads are running. Quit anyway?"):
            return
        self.save_cfg()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    main()
