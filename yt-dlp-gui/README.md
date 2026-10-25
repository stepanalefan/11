# Ultimate Video Downloader (yt-dlp GUI)

A single-file desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp). It downloads from YouTube and the other 1,800+ sites yt-dlp supports.

## Install & run

```bash
pip install -r requirements.txt
python ytdlp_gui.py
```

- **ffmpeg** must be on your PATH for merging video and audio, converting audio, and embedding. The app warns you at startup if it can't find it.
- On Linux, Tkinter may need installing separately (`sudo apt install python3-tk`).
- If yt-dlp is missing when you launch, the app offers to install it.

## Features

- **Queue**: paste many URLs (videos, playlists, channels). Run 1–8 downloads in parallel, with live progress, speed, ETA and size. You can cancel, retry failed downloads and clear finished ones.
- **Presets**: best quality, MP4 (H.264/AAC), WebM, video only, and MP3 / M4A / Opus / FLAC / WAV / original audio.
- **Max resolution** cap (2160p down to 240p).
- **Format inspector** (`Formats…`): lists every stream for a URL. Pick one stream, or a video and an audio stream to merge.
- **Playlists**: download the whole playlist or only some items (`1-5,8`).
- **Subtitles**: manual or auto-generated, with language patterns, optionally embedded in the video.
- **Embedding**: thumbnail, metadata and chapters.
- **SponsorBlock**: mark segments as chapters, or cut sponsors or all segments out.
- **Network & auth**: cookies from your browser or a `cookies.txt` file, a rate limit, a proxy, and the number of fragments downloaded at once.
- **Download archive**: skips videos you've already downloaded.
- Custom filename template and ASCII-safe filenames.
- **Update yt-dlp** button.
- Your settings are saved to `~/.ytdlp_gui.json`.

Shortcut: `Ctrl+Enter` starts the download.

Only download content you have the right to download.
