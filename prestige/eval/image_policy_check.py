"""Paired live check of the image policy, through the gateway, on Muse Spark. About $0.10.

    python -m prestige.eval.image_policy_check --trials 2

A plain OpenAI SDK agent sends a 6-step conversation of rendered frames with its full history, the way
agents do. A cube moves left to right, and each step asks where it is, so every answer has a known
right one. The same conversation goes through gateways that differ only in the image setting. Prints
counts, costs and accuracy only.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from harness.adapters import MuseAdapter
from harness.serve import parse_policies
from openai import OpenAI

from prestige.__main__ import load_env
from prestige.eval.images import frame
from prestige.gateway import build_server

SETUPS = (
    ("no image policy", None),
    ("max side 512", {"max_side": 512, "keep_last": None}),
    ("max side 512, keep last 2", {"max_side": 512, "keep_last": 2}),
)
QUESTION = "Answer with one word, left, center or right: where is the cube in the newest frame?"


def truth(step: int) -> str:
    x = 0.25 + 0.1 * step  # where frame() draws the cube, as a share of the width
    return "left" if x < 0.4 else "center" if x <= 0.6 else "right"


def conversation(base_url: str) -> tuple[int, int]:
    client = OpenAI(base_url=base_url, api_key="unused")
    messages = [{"role": "system", "content": "You track an object across frames of a render."}]
    right = 0
    for step in range(6):
        messages.append({"role": "user", "content": [{"type": "text", "text": QUESTION}, {"type": "image_url", "image_url": {"url": frame(step, 1024, 768)}}]})
        reply = client.chat.completions.create(model="muse-spark-1.3", messages=messages).choices[0].message.content or ""
        messages.append({"role": "assistant", "content": reply})
        words = reply.lower()
        right += truth(step) in words and sum(w in words for w in ("left", "center", "right")) == 1
    return right, 6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.image_policy_check", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--max-total", type=float, default=0.5, help="spend cap across all setups, in USD")
    args = parser.parse_args(argv)
    load_env()
    adapter = MuseAdapter("https://api.meta.ai/v1")
    chain = parse_policies("cache,reason", ["reason.escalate=false"])  # Prestige's cost policies, as in the main runs
    from harness.budget import SpendLimit

    for label, images in SETUPS:
        db = Path(tempfile.mkdtemp()) / "trace.sqlite"
        server = build_server(adapter, chain=chain, guard=None, db=str(db), port=0, limit=SpendLimit(args.max_total / len(SETUPS)), images=images)
        try:
            right = total = 0
            for trial in range(args.trials):
                r, n = conversation(server.proxy.url_for(f"images-{trial}"))
                right, total = right + r, total + n
            row = server.store.connection.execute(
                "SELECT sum(input_tokens), sum(cached_input_tokens), sum(cost_uncached_input + cost_cached_input), sum(cost_output) FROM calls"
            ).fetchone()
        finally:
            server.stop()
        print(json.dumps({"setup": label, "input_tokens": row[0], "cached": row[1], "input_cost": round(row[2], 5), "output_cost": round(row[3], 5), "right": right, "of": total}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
