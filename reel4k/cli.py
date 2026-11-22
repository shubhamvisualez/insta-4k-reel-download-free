"""reel4k — download a public Instagram Reel and export it as a 4K MP4.

Pipeline:
  1. Fetch the highest-quality video + audio streams Instagram serves (via yt-dlp).
  2. Merge them into an MP4.
  3. Optionally upscale to 4K (3840 px on the long edge) with a Lanczos filter.

Note: Instagram itself stores most Reels at up to 1080x1920. Step 3 produces a
4K-resolution file, but it cannot add detail that was never uploaded. Use
--no-upscale to keep the original resolution.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yt_dlp

URL_RE = re.compile(
    r"^https?://(www\.)?instagram\.com/(?:[\w.]+/)?(reel|reels|p|tv)/([\w-]+)/?",
    re.IGNORECASE,
)

TARGET_LONG_EDGE = 3840  # 4K UHD long edge
TARGET_SHORT_EDGE = 2160


def find_ffmpeg() -> str:
    """Return a usable ffmpeg binary: system one first, bundled one as fallback."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        sys.exit(f"error: ffmpeg not found ({exc}). Install it: brew install ffmpeg")


def parse_url(url: str) -> str:
    m = URL_RE.match(url.strip())
    if not m:
        sys.exit(
            "error: that doesn't look like an Instagram Reel/post URL.\n"
            "       expected e.g. https://www.instagram.com/reel/ABC123xyz/"
        )
    return m.group(3)


def probe(ffmpeg: str, path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream using ffmpeg -i output."""
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def probe_duration(ffmpeg: str, path: Path) -> float:
    """Return the media duration in seconds (0 if unknown)."""
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def download(
    url: str, workdir: Path, ffmpeg: str, cookies_browser: str | None, on_progress=None
) -> tuple[Path, dict]:
    opts = {
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        # best video + best audio, prefer highest resolution, then bitrate
        "format": "bv*+ba/b",
        "format_sort": ["res", "br", "fps", "vcodec:h264"],
        "merge_output_format": "mp4",
        "ffmpeg_location": ffmpeg,
        "quiet": True,
        "no_warnings": True,
        "noprogress": False,
        # Instagram sometimes stalls requests from cloud servers: wait longer and retry
        "socket_timeout": 45,
        "retries": 5,
        "extractor_retries": 4,
        "fragment_retries": 5,
        "retry_sleep_functions": {"http": lambda n: 2 * (n + 1), "extractor": lambda n: 3 * (n + 1)},
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    if on_progress:
        def hook(d):
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if d.get("status") == "downloading" and total:
                on_progress(min(d.get("downloaded_bytes", 0) / total, 1.0))
        opts["progress_hooks"] = [hook]
        opts["noprogress"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist":  # carousel posts
            entries = [e for e in info.get("entries") or [] if e and e.get("vcodec") != "none"]
            if not entries:
                sys.exit("error: no video found in that post.")
            info = entries[0]

    files = sorted(workdir.glob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        sys.exit("error: download finished but no MP4 was produced.")
    return files[0], info


def upscale(
    ffmpeg: str, src: Path, dst: Path, w: int, h: int, crf: int, preset: str, on_progress=None
) -> None:
    """Scale src to 4K. on_progress(fraction) is called as encoding advances, if given."""
    if h >= w:  # portrait (typical Reel) -> 2160x3840
        scale = f"scale={TARGET_SHORT_EDGE}:{TARGET_LONG_EDGE}:force_original_aspect_ratio=decrease:flags=lanczos"
        pad = f"pad={TARGET_SHORT_EDGE}:{TARGET_LONG_EDGE}:(ow-iw)/2:(oh-ih)/2"
    else:  # landscape -> 3840x2160
        scale = f"scale={TARGET_LONG_EDGE}:{TARGET_SHORT_EDGE}:force_original_aspect_ratio=decrease:flags=lanczos"
        pad = f"pad={TARGET_LONG_EDGE}:{TARGET_SHORT_EDGE}:(ow-iw)/2:(oh-ih)/2"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        *(["-progress", "pipe:1", "-nostats"] if on_progress else ["-stats"]),
        "-i", str(src),
        "-vf", f"{scale},{pad},setsar=1",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "5.1",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(dst),
    ]
    if not on_progress:
        subprocess.run(cmd, check=True)
        return
    duration = probe_duration(ffmpeg, src)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if line.startswith("out_time_us=") and duration:
            try:
                done_s = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            on_progress(max(0.0, min(done_s / duration, 1.0)))
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()[-300:]}")


class ReelError(Exception):
    """Raised by fetch_reel with a message suitable for end users."""


def fetch_reel(
    url: str,
    outdir: Path,
    to_4k: bool = True,
    crf: int = 16,
    preset: str = "slow",
    cookies_browser: str | None = None,
    log=lambda msg: None,
    progress=None,
) -> dict:
    """progress(fraction, message), if given, is called with overall progress from 0 to 1."""
    best = [0.0]

    def report(frac: float, msg: str) -> None:
        # video and audio download separately, so never let the bar move backwards
        best[0] = max(best[0], frac)
        if progress:
            progress(best[0], msg)
    """Download a Reel into outdir and return a summary dict. Used by the web app."""
    m = URL_RE.match(url.strip())
    if not m:
        raise ReelError("That doesn't look like an Instagram Reel link, e.g. https://www.instagram.com/reel/ABC123xyz/")
    shortcode = m.group(3)
    ffmpeg = find_ffmpeg()
    outdir.mkdir(parents=True, exist_ok=True)
    final = outdir / f"{shortcode}{'_4k' if to_4k else ''}.mp4"

    with tempfile.TemporaryDirectory(prefix="reel4k-") as tmp:
        log("Fetching the best available video from Instagram…")
        report(0.02, "Downloading from Instagram…")
        try:
            src, info = download(
                url.strip(), Path(tmp), ffmpeg, cookies_browser,
                on_progress=lambda f: report(0.02 + 0.18 * f, f"Downloading from Instagram… {f:.0%}"),
            )
        except yt_dlp.utils.DownloadError as exc:
            text = str(exc).lower()
            if "timed out" in text or "timeout" in text or "429" in text or "rate" in text:
                raise ReelError(
                    "Instagram is busy or limiting requests from this server right now. "
                    "Please wait a minute and try again."
                ) from exc
            raise ReelError(
                "Instagram didn't return this video. Make sure the account is public and the link is correct. "
                f"({str(exc).replace('ERROR: ', '')[:200]})"
            ) from exc
        w, h = probe(ffmpeg, src)
        log(f"Source resolution: {w}x{h}")
        if not to_4k or max(w, h) >= TARGET_LONG_EDGE:
            shutil.move(str(src), final)
        else:
            log("Exporting 4K…")
            report(0.2, "Exporting 4K… 0%")
            upscale(
                ffmpeg, src, final, w, h, crf, preset,
                on_progress=lambda f: report(0.2 + 0.8 * f, f"Exporting 4K… {f:.0%}"),
            )

    fw, fh = probe(ffmpeg, final)
    return {
        "id": shortcode,
        "uploader": info.get("uploader") or info.get("channel"),
        "source_resolution": f"{w}x{h}",
        "output_resolution": f"{fw}x{fh}",
        "file": str(final.resolve()),
        "size_mb": round(final.stat().st_size / 1_048_576, 2),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="reel4k",
        description="Download a public Instagram Reel and export it as a 4K MP4.",
    )
    p.add_argument("url", help="public Instagram Reel URL, e.g. https://www.instagram.com/reel/ABC123/")
    p.add_argument("-o", "--output", type=Path, default=Path("downloads"),
                   help="output directory or .mp4 file path (default: ./downloads)")
    p.add_argument("--no-upscale", action="store_true",
                   help="keep Instagram's original resolution instead of exporting 4K")
    p.add_argument("--crf", type=int, default=16,
                   help="x264 quality for the 4K export, lower = better/larger (default: 16)")
    p.add_argument("--preset", default="slow",
                   help="x264 speed preset for the 4K export (default: slow)")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="use cookies from a browser (chrome, safari, firefox...) if Instagram rate-limits you")
    p.add_argument("--json", action="store_true", help="print a JSON summary when done")
    args = p.parse_args(argv)

    shortcode = parse_url(args.url)
    ffmpeg = find_ffmpeg()

    out = args.output
    if out.suffix.lower() == ".mp4":
        out.parent.mkdir(parents=True, exist_ok=True)
        final = out
    else:
        out.mkdir(parents=True, exist_ok=True)
        final = out / f"{shortcode}{'' if args.no_upscale else '_4k'}.mp4"

    with tempfile.TemporaryDirectory(prefix="reel4k-") as tmp:
        print(f"→ fetching best available streams for {shortcode} …", file=sys.stderr)
        try:
            src, info = download(args.url, Path(tmp), ffmpeg, args.cookies_from_browser)
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc)
            hint = ""
            if "login" in msg.lower() or "rate" in msg.lower() or "empty media" in msg.lower():
                hint = "\nhint: try --cookies-from-browser chrome (or safari/firefox)."
            print(f"error: {msg}{hint}", file=sys.stderr)
            return 1

        w, h = probe(ffmpeg, src)
        print(f"→ source resolution: {w}x{h}", file=sys.stderr)

        if args.no_upscale or max(w, h) >= TARGET_LONG_EDGE:
            if max(w, h) >= TARGET_LONG_EDGE:
                print("→ source is already 4K, saving as-is", file=sys.stderr)
            shutil.move(str(src), final)
        else:
            print(f"→ exporting 4K (Lanczos upscale, crf {args.crf}, preset {args.preset}) …", file=sys.stderr)
            upscale(ffmpeg, src, final, w, h, args.crf, args.preset)

    fw, fh = probe(ffmpeg, final)
    summary = {
        "url": args.url,
        "id": shortcode,
        "uploader": info.get("uploader") or info.get("channel"),
        "source_resolution": f"{w}x{h}",
        "output_resolution": f"{fw}x{fh}",
        "file": str(final.resolve()),
        "size_mb": round(final.stat().st_size / 1_048_576, 2),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"✓ saved {summary['file']} ({fw}x{fh}, {summary['size_mb']} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
