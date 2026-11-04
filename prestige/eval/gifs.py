"""Animated GIFs of two measured results: the image policy on 3D renders, and the guard on IBM's Qiskit tools.

    python -m prestige.eval.gifs --out docs/figures

Every number shown is a measured one from docs/IMAGES.md and docs/RESULTS.md. The renders are the ones
the live image probes sent, drawn by `prestige.eval.images.frame`. Needs Pillow.
"""

from __future__ import annotations

import argparse
import base64
import io
from pathlib import Path

from prestige.assistant import FACES, NAME
from prestige.eval.assistant_gif import INK, MOOD, font
from prestige.eval.images import frame as render

BG, PANEL, TEXT, MUTED = "#1a1a19", "#242422", "#f0efec", "#9a988f"
BLUE, ORANGE, GREEN, RED = "#3987e5", "#d95926", "#56c597", "#e66767"

# Measured on Muse Spark 1.3, Nov 4 (docs/IMAGES.md)
TOKENS_FULL, TOKENS_SMALL = 974, 268  # input tokens for one 1024x768 render, and for the same render at 512x384
RESULT = [
    "Measured through the gateway, 2 trials of 6 steps:",
    "input tokens -70%, input cost -55%,",
    "answers right 10 of 12, against 12 of 12 at full size.",
]


def _image(url: str):
    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def pipeline_frame(step: int, phase: int, full_so_far: int, small_so_far: int, closing: bool = False):
    """One frame of the image pipeline. phase 0: the render arrives, 1: it's downscaled, 2: tokens counted."""
    from PIL import Image, ImageDraw

    w, h = 760, 460
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    f, small, big = font(15), font(13), font(17)
    d.text((24, 18), "Agent", font=big, fill=TEXT)
    d.text((300, 18), "Prestige gateway", font=big, fill=TEXT)
    d.text((560, 18), "Muse Spark", font=big, fill=TEXT)
    d.text((24, 42), f"step {step + 1} of 6, the render the agent sends", font=small, fill=MUTED)

    full = _image(render(step, 1024, 768)).resize((256, 192))
    img.paste(full, (24, 70))
    d.text((24, 268), "1024 x 768", font=f, fill=TEXT)
    d.text((24, 288), f"{TOKENS_FULL} input tokens", font=small, fill=MUTED)

    if phase >= 1:
        d.line([(296, 166), (520, 166)], fill=BLUE, width=3)
        d.polygon([(520, 158), (536, 166), (520, 174)], fill=BLUE)
        d.text((316, 138), "--image-max-side 512", font=small, fill=BLUE)
        shrunk = _image(render(step, 512, 384)).resize((128, 96))
        img.paste(shrunk, (552, 118))
        d.text((552, 222), "512 x 384", font=f, fill=TEXT)
        d.text((552, 242), f"{TOKENS_SMALL} input tokens", font=small, fill=MUTED)

    # input tokens so far, both ways, on one scale
    top = 330
    d.text((24, top), "Image tokens so far, every earlier render resent each step", font=small, fill=MUTED)
    scale = (w - 200) / (TOKENS_FULL * 21)
    for i, (label, value, color) in enumerate((("without", full_so_far, ORANGE), ("with", small_so_far, BLUE))):
        y = top + 22 + i * 30
        d.text((24, y + 2), label, font=small, fill=TEXT)
        if value:
            d.rounded_rectangle([96, y, 96 + max(6, value * scale), y + 20], radius=4, fill=color)
        d.text((104 + value * scale, y + 2), f"{value:,}", font=small, fill=TEXT)
    if full_so_far:
        cut = 100 * (1 - small_so_far / full_so_far)
        d.text((w - 24, top), f"-{cut:.0f}% image tokens", font=big, fill=BLUE, anchor="ra")

    if closing:
        d.rectangle([0, 0, w, h], fill=BG)
        d.text((24, 30), "Downscaling 3D renders in the gateway", font=big, fill=TEXT)
        y = 80
        for line in RESULT:
            d.text((24, y), line, font=big, fill=TEXT)
            y += 30
        d.text((24, y + 20), "Off by default. Check accuracy on your own task first.", font=f, fill=MUTED)
        d.text((24, y + 46), "prestige serve ... --image-max-side 512", font=f, fill=BLUE)
        img.paste(_image(render(5, 1024, 768)).resize((256, 192)), (24, 240))
        img.paste(_image(render(5, 512, 384)).resize((128, 96)), (320, 336))
        d.text((24, 438), "1024 x 768", font=small, fill=MUTED)
        d.text((320, 438), "512 x 384", font=small, fill=MUTED)
    return img


def image_pipeline_gif(out: Path) -> None:
    frames, durations = [], []
    full = small = 0
    for step in range(6):
        for phase in range(3):
            if phase == 2:  # the request carries every image so far
                full += TOKENS_FULL * (step + 1)
                small += TOKENS_SMALL * (step + 1)
            frames.append(pipeline_frame(step, phase, full, small))
            durations.append((700, 700, 900)[phase])
    frames.append(pipeline_frame(5, 2, full, small, closing=True))
    durations.append(4200)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)


# The live Qiskit checks, Nov 3 and 4 (docs/RESULTS.md). (mood, new log lines, what a line means)
QISKIT = [
    ("look", [("IBM Qiskit MCP server, 20 tools. Labels drafted from its schemas.", MUTED)]),
    ("look", [("you: list my jobs and cancel the queued one", TEXT), ("list_my_jobs_tool()                      read", GREEN)]),
    ("alarm", [("cancel_job_tool(job_id)                  BLOCKED", RED), ("  draft labels: job_id came from list_my_jobs_tool", MUTED)]),
    ("look", [("review: IBM's 15 read tools marked as trusted output", BLUE)]),
    ("happy", [("cancel_job_tool(job_id)                  cancelled", GREEN)]),
    ("look", [("you: read job_sheet.txt and submit the job", TEXT), ("read_file(path)                          read", GREEN)]),
    ("alarm", [("run_sampler_tool(backend_name, shots)    BLOCKED", RED)]),
    ("stern", [("  backend_name and shots came only from read_file", MUTED)]),
    ("cheer", [("Live on Muse Spark. No IBM account, no quantum hardware.", MUTED)]),
]


def qiskit_frame(mood: str, lines: list[tuple[str, str]]):
    from PIL import Image, ImageDraw

    w, h = 960, 360
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    f, small = font(15), font(14)
    d.rectangle([0, 0, w, 30], fill=PANEL)
    for i, color in enumerate((RED, "#e3b24a", GREEN)):
        d.ellipse([14 + i * 20, 10, 24 + i * 20, 20], fill=color)
    d.text((w / 2, 15), "prestige assistant  ·  IBM Qiskit tools", font=small, fill=MUTED, anchor="mm")
    y = 50
    for row in FACES[mood]:
        d.text((16, y), row, font=f, fill=INK[MOOD[mood]])
        y += 20
    pad = " " * ((len(FACES["cheer"][0]) - len(NAME)) // 2)
    d.text((16, y + 4), pad + NAME, font=f, fill=TEXT)
    x, y = 330, 52
    for text, color in lines[-16:]:
        d.text((x, y), text, font=small, fill=color)
        y += 24
    return img


def qiskit_gif(out: Path) -> None:
    frames, durations, log = [], [], []
    for mood, new in QISKIT:
        log.extend(new)
        frames.append(qiskit_frame(mood, list(log)))
        durations.append(2600 if mood in ("alarm", "stern", "cheer") else 1600)
    durations[-1] = 4000
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.gifs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="docs/figures")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    image_pipeline_gif(out / "image-pipeline.gif")
    qiskit_gif(out / "qiskit.gif")
    print(f"wrote {out / 'image-pipeline.gif'} and {out / 'qiskit.gif'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
