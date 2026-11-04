"""An animated GIF of `prestige assistant` going through one guarded session.

    python -m prestige.eval.assistant_gif --out docs/figures/assistant.gif

Faces and wording come from `prestige.assistant`, so the GIF shows what the terminal shows. Needs
Pillow (`pip install "prestige[figures]"`) and a monospace font.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prestige.assistant import FACES, NAME

BG = "#1a1a19"
INK = {"37": "#e8e2d0", "31": "#e66767", "33": "#e3b24a", "32": "#56c597"}  # the terminal colors, as hex
MOOD = {"idle": "37", "blink": "37", "look": "37", "alarm": "31", "stern": "33", "happy": "32", "cheer": "32"}
TEXT, MUTED, BAR = "#f0efec", "#8f8d86", "#2a2a28"
FONTS = ("C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
MODEL = "muse-spark-1.3"
SPEND_START = "$0.00 spent of $0.50 cap, $0.50 left"
SPEND_END = "$0.04 spent of $0.50 cap, $0.46 left"

# (mood, lines under the face, spend line or None, milliseconds)
SCENES = [
    ("idle", ["Hi. I watch your agent's tool calls.", "Type help to see what I can do."], None, 1400),
    ("blink", ["Hi. I watch your agent's tool calls.", "Type help to see what I can do."], None, 160),
    ("idle", ["Hi. I watch your agent's tool calls.", "Type help to see what I can do."], None, 700),
    ("look", ["Watching runs/prestige.sqlite.", "Ctrl+C to stop."], SPEND_START, 1500),
    ("alarm", ["The agent wants to run send_money.recipient", "with 'ACCT-TEST-9999'.", "That value came only from read_file, never from you."], SPEND_START, 900),
    ("look", ["The agent wants to run send_money.recipient", "with 'ACCT-TEST-9999'.", "That value came only from read_file, never from you.", "Let it through? [y/N]"], SPEND_START, 1100),
    ("look", ["The agent wants to run send_money.recipient", "with 'ACCT-TEST-9999'.", "That value came only from read_file, never from you.", "Let it through? [y/N] n"], SPEND_START, 600),
    ("happy", ["Blocked it."], SPEND_START, 1300),
    ("alarm", ["Blocked get_webpage.url.", "Its value came only from get_webpage."], SPEND_START, 500),
    ("stern", ["Blocked get_webpage.url.", "Its value came only from get_webpage."], SPEND_START, 1500),
    ("happy", ["All done.", "Saved by the prompt cache: $0.03.", "Calls the guard stopped: 2."], SPEND_END, 500),
    ("cheer", ["All done.", "Saved by the prompt cache: $0.03.", "Calls the guard stopped: 2."], SPEND_END, 2600),
]


def font(size: int):
    from PIL import ImageFont

    for path in FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def frame(mood: str, lines: list[str], spend: str | None, size: int = 18):
    from PIL import Image, ImageDraw

    f, small = font(size), font(size - 4)
    step = int(size * 1.35)
    width, height = 640, 40 + step * 17
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 30], fill=BAR)  # a terminal title bar
    for i, color in enumerate(("#e66767", "#e3b24a", "#56c597")):
        d.ellipse([14 + i * 20, 10, 24 + i * 20, 20], fill=color)
    y = 44
    for row in FACES[mood]:
        d.text((24, y), row, font=f, fill=INK[MOOD[mood]])
        y += step
    pad = " " * ((len(FACES["cheer"][0]) - len(NAME)) // 2)
    d.text((24, y), pad + NAME, font=f, fill=TEXT)
    y += step
    model_pad = " " * ((len(FACES["cheer"][0]) - len(MODEL)) // 2)
    d.text((24, y), model_pad + MODEL, font=small, fill=MUTED)
    y += step
    for line in lines:
        d.text((24, y), "  " + line, font=f, fill=TEXT)
        y += step
    if spend:
        d.text((24, y), "  " + spend, font=small, fill=MUTED)
    return img


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.assistant_gif", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="docs/figures/assistant.gif")
    args = parser.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        print('needs Pillow: pip install "prestige[figures]"', file=sys.stderr)
        return 2
    frames = [frame(mood, lines, spend) for mood, lines, spend, _ in SCENES]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=[ms for *_, ms in SCENES], loop=0, optimize=True)
    print(f"wrote {out}, {len(frames)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
