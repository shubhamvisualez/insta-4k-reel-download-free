# reel4k

Paste the link to a public Instagram Reel and get a **4K MP4** (2160×3840 portrait / 3840×2160 landscape).

```bash
reel4k "https://www.instagram.com/reel/ABC123xyz/"
# → downloads/ABC123xyz_4k.mp4  (2160x3840)
```

## How it works

1. **Fetch.** [yt-dlp](https://github.com/yt-dlp/yt-dlp) gets the highest-resolution video stream and the best audio stream Instagram serves for the Reel.
2. **Merge.** Video and audio are combined into one MP4.
3. **Export 4K.** ffmpeg scales the video to 3840 px on the long edge with a Lanczos filter and encodes it as high-bitrate H.264 (CRF 16). The audio is copied without re-encoding.

> **About "4K".** Instagram stores almost every Reel at **1080×1920 at most**, so no tool can download a true 4K original. reel4k gets the best source available and upscales it cleanly to a 4K-resolution file, which is useful for editing timelines, 4K exports and big screens. It can't add detail that was never uploaded. If a source is already 4K or larger, reel4k keeps it as-is. Use `--no-upscale` to keep the original file.

## Install

Requires Python 3.10+. ffmpeg comes bundled through `imageio-ffmpeg`. If you have ffmpeg installed system-wide, reel4k uses that one.

```bash
git clone https://github.com/shubhamvisualez/reel4k.git
cd reel4k
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Usage

```bash
reel4k <url> [options]
```

| Option | Description |
|---|---|
| `-o, --output PATH` | Output folder or `.mp4` file path (default `./downloads`) |
| `--no-upscale` | Keep Instagram's original resolution |
| `--crf N` | x264 quality for the 4K export. Lower is better quality and a larger file (default `16`) |
| `--preset NAME` | x264 speed preset: `ultrafast` … `veryslow` (default `slow`) |
| `--cookies-from-browser B` | Use cookies from `chrome`, `safari`, `firefox`, … if Instagram rate-limits or asks for a login |
| `--json` | Print a JSON summary when done |

Examples:

```bash
# Faster 4K export
reel4k "https://www.instagram.com/reel/ABC123xyz/" --preset fast

# Original quality only, no upscale
reel4k "https://www.instagram.com/reel/ABC123xyz/" --no-upscale

# Save to a specific file
reel4k "https://www.instagram.com/reel/ABC123xyz/" -o ~/Movies/clip.mp4
```

You can also run it with `python -m reel4k <url>`.

## Troubleshooting

- **"login required" / rate-limit errors.** Instagram sometimes blocks anonymous requests. Add `--cookies-from-browser chrome` (or the browser where you're logged in to Instagram).
- **Extraction broke suddenly.** Instagram changes often. Update yt-dlp with `pip install -U yt-dlp`.

## Legal

Only download content you own or have permission to use. Respect creators' rights and [Instagram's Terms of Use](https://help.instagram.com/581066165581870). This project isn't affiliated with Instagram or Meta.

## License

MIT
