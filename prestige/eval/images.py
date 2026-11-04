"""What images cost on Muse Spark, measured live. About $0.06 a run. Prints token counts only.

    python -m prestige.eval.images probe     # one image at three sizes, and the same image twice
    python -m prestige.eval.images history   # a 6-step image conversation, full history against the last 2

The images are rendered here: a lit cube on a perspective floor, standing in for a 3D render or a
screenshot. Needs Pillow (`pip install "prestige[figures]"`) and HARNESS_API_KEY. Results are in
docs/IMAGES.md.
"""

from __future__ import annotations

import base64
import io
import json
import sys

from harness.adapters import MuseAdapter
from PIL import Image, ImageDraw

from prestige.__main__ import load_env

P_IN, P_CACHED = 1.25e-6, 0.15e-6
SYSTEM_PROBE = {"role": "system", "content": "You describe images for a rendering pipeline. Answer in at most six words."}


def adapter() -> MuseAdapter:
    load_env()
    return MuseAdapter("https://api.meta.ai/v1")


def scene(w: int, h: int) -> str:
    """A rendered 3D-looking scene: a shaded floor grid and a lit cube, as a PNG data URL."""
    img = Image.new("RGB", (w, h), (24, 26, 34))
    d = ImageDraw.Draw(img)
    for i in range(0, 21):  # perspective floor grid
        x = i * w / 20
        d.line([(w / 2, h * 0.45), (x, h)], fill=(70, 80, 110), width=max(1, w // 512))
    for j in range(1, 12):
        y = h * 0.45 + (h * 0.55) * (j / 11) ** 1.6
        d.line([(0, y), (w, y)], fill=(70, 80, 110), width=max(1, w // 512))
    s = w * 0.16
    cx, cy = w * 0.5, h * 0.55
    top = [(cx, cy - s), (cx + s, cy - s * 0.5), (cx, cy), (cx - s, cy - s * 0.5)]
    left = [(cx - s, cy - s * 0.5), (cx, cy), (cx, cy + s), (cx - s, cy + s * 0.5)]
    right = [(cx + s, cy - s * 0.5), (cx, cy), (cx, cy + s), (cx + s, cy + s * 0.5)]
    d.polygon(top, fill=(230, 160, 70))
    d.polygon(left, fill=(170, 100, 40))
    d.polygon(right, fill=(120, 70, 30))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def ask(muse: MuseAdapter, images: list[str], label: str) -> None:
    content = [{"type": "text", "text": "What is in this render?"}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
    req = {"model": "muse-spark-1.3", "messages": [SYSTEM_PROBE, {"role": "user", "content": content}], "max_completion_tokens": 400}
    u = muse.call("chat_completions", req).usage
    print(json.dumps({"label": label, "input": u.input_tokens, "cached": u.cached_input_tokens, "output": u.output_tokens}))


def probe() -> None:
    muse = adapter()
    full, half, quarter = scene(1024, 768), scene(512, 384), scene(256, 192)
    ask(muse, [], "no image")
    ask(muse, [full], "1024x768")
    ask(muse, [full], "1024x768 again")
    ask(muse, [half], "512x384")
    ask(muse, [quarter], "256x192")
    ask(muse, [full, full, full], "three copies of 1024x768")


def frame(step: int, w: int, h: int) -> str:
    """Step `step` of a rendered scene: the cube moves and changes shade each step."""
    img = Image.new("RGB", (w, h), (24, 26, 34))
    d = ImageDraw.Draw(img)
    for i in range(21):
        d.line([(w / 2, h * 0.45), (i * w / 20, h)], fill=(70, 80, 110), width=max(1, w // 512))
    s, cx, cy = w * 0.14, w * (0.25 + 0.1 * step), h * 0.6
    shade = 120 + 20 * step
    d.polygon([(cx, cy - s), (cx + s, cy - s / 2), (cx, cy), (cx - s, cy - s / 2)], fill=(shade, 140, 60))
    d.polygon([(cx - s, cy - s / 2), (cx, cy), (cx, cy + s), (cx - s, cy + s / 2)], fill=(shade - 60, 90, 40))
    d.polygon([(cx + s, cy - s / 2), (cx, cy), (cx, cy + s), (cx + s, cy + s / 2)], fill=(shade - 90, 60, 30))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def run(muse: MuseAdapter, keep: int | None, w: int, h: int) -> dict:
    system = {"role": "system", "content": "You track an object across frames of a render. Reply in at most eight words."}
    turns = []  # (image url, reply)
    totals = {"input": 0, "cached": 0, "output": 0}
    for step in range(6):
        url = frame(step, w, h)
        turns.append([url, None])
        kept = turns if keep is None else turns[-keep:]
        messages = [system]
        for i, (u, reply) in enumerate(kept):
            messages.append({"role": "user", "content": [{"type": "text", "text": "Next frame. Where is the cube now?"}, {"type": "image_url", "image_url": {"url": u}}]})
            if reply is not None:
                messages.append({"role": "assistant", "content": reply})
        r = muse.call("chat_completions", {"model": "muse-spark-1.3", "messages": messages, "reasoning_effort": "low", "max_completion_tokens": 300})
        turns[-1][1] = (r.response["choices"][0]["message"].get("content") or "ok")[:80]
        totals["input"] += r.usage.input_tokens
        totals["cached"] += r.usage.cached_input_tokens
        totals["output"] += r.usage.output_tokens
    cost_in = (totals["input"] - totals["cached"]) * P_IN + totals["cached"] * P_CACHED
    return {**totals, "input_cost": round(cost_in, 5), "cache_share": round(totals["cached"] / totals["input"], 3)}


def history() -> None:
    muse = adapter()
    for label, keep, w, h in [("full history, 1024x768", None, 1024, 768), ("last 2 images, 1024x768", 2, 1024, 768),
                              ("full history, 512x384", None, 512, 384), ("last 2 images, 512x384", 2, 512, 384)]:
        print(json.dumps({"run": label, **run(muse, keep, w, h)}))


def main(argv: list[str] | None = None) -> int:
    which = (argv if argv is not None else sys.argv[1:])[:1]
    if which == ["probe"]:
        probe()
    elif which == ["history"]:
        history()
    else:
        print("usage: python -m prestige.eval.images probe|history", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
