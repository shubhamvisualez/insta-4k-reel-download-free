"""Web app: paste a public Instagram Reel link and download it as a 4K MP4.

Run locally:  python app.py
Hosted on Hugging Face Spaces (Gradio SDK).
"""

from __future__ import annotations

import os
import shutil
import time
import tempfile
import uuid
from pathlib import Path

import gradio as gr

from reel4k.cli import ReelError, fetch_reel

TITLE = "Insta 4K Reel Download Free"
OUT_ROOT = Path(os.environ.get("REEL4K_OUT", Path(tempfile.gettempdir()) / "reel4k-web"))
MAX_AGE_S = 60 * 60  # delete generated files after an hour
PRESET = os.environ.get("REEL4K_PRESET", "veryfast")
CRF = int(os.environ.get("REEL4K_CRF", "18"))


def cleanup() -> None:
    if not OUT_ROOT.exists():
        return
    now = time.time()
    for d in OUT_ROOT.iterdir():
        if now - d.stat().st_mtime > MAX_AGE_S:
            shutil.rmtree(d, ignore_errors=True)


def run(url: str, quality: str, progress=gr.Progress()):
    cleanup()
    if not url or not url.strip():
        raise gr.Error("Paste an Instagram Reel link first.")
    job = OUT_ROOT / uuid.uuid4().hex[:12]
    to_4k = quality.startswith("4K")
    steps = iter([0.1, 0.5, 0.6, 0.9])
    try:
        info = fetch_reel(
            url, job, to_4k=to_4k, crf=CRF, preset=PRESET,
            log=lambda msg: progress(next(steps, 0.95), desc=msg),
        )
    except ReelError as exc:
        shutil.rmtree(job, ignore_errors=True)
        raise gr.Error(str(exc))
    except Exception as exc:  # unexpected failure
        shutil.rmtree(job, ignore_errors=True)
        raise gr.Error(f"Something went wrong: {exc}")

    note = ""
    if to_4k and info["source_resolution"] != info["output_resolution"]:
        note = (
            f"\n\nInstagram served this Reel at **{info['source_resolution']}**. "
            "It was upscaled to 4K, which can't add detail that wasn't uploaded."
        )
    summary = (
        f"✅ **Ready:** {info['output_resolution']} · {info['size_mb']} MB"
        + (f" · by {info['uploader']}" if info.get("uploader") else "")
        + note
    )
    return info["file"], summary


with gr.Blocks(title=TITLE) as demo:
    gr.Markdown(
        f"# 🎬 {TITLE}\n"
        "Paste the link to a **public** Instagram Reel and download it as a 4K MP4. Free, no login."
    )
    url = gr.Textbox(
        label="Instagram Reel link",
        placeholder="https://www.instagram.com/reel/ABC123xyz/",
        autofocus=True,
    )
    quality = gr.Radio(
        ["4K (2160×3840)", "Original quality (faster)"],
        value="4K (2160×3840)",
        label="Quality",
    )
    btn = gr.Button("Download", variant="primary")
    status = gr.Markdown()
    out = gr.File(label="Your video")

    btn.click(run, [url, quality], [out, status])
    url.submit(run, [url, quality], [out, status])

    gr.Markdown(
        "<small>4K export on this free server takes about twice the Reel's length (a 1-minute Reel takes about 2 minutes). Choose Original quality for an instant download. "
        "Instagram stores most Reels at up to 1080×1920, so the 4K file is upscaled from the best available source. "
        "Only download content you own or have permission to use. Not affiliated with Instagram or Meta. "
        "[Source code](https://github.com/shubhamvisualez/insta-4k-reel-download-free)</small>"
    )

demo.queue(default_concurrency_limit=2, max_size=20)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)), theme=gr.themes.Soft())
