"""An opt-in cost policy for agents that send images: downscale them, and trim old ones.

    prestige serve ... --image-max-side 512 --image-keep-last 2

Measured on Muse Spark (docs/IMAGES.md): image tokens scale with pixel count, so halving each side cuts
an image's cost by about 72%. Old images in the history are billed again on every turn. Trimming them
breaks the cache prefix, which only pays when the provider caches the history poorly, as Muse did.

Only images embedded as `data:` URLs are resized. Remote URLs pass through, since the gateway doesn't
fetch anything. The same image always resizes to the same bytes, so a repeated history stays a
repeated prefix for the provider's cache. Resizing needs Pillow (`pip install "prestige[figures]"`).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
from typing import Any

from harness.policies.base import Policy, SessionContext
from harness.usage import Protocol

DROPPED = "[an earlier image was removed by the gateway to save tokens]"


def _images(protocol: Protocol, request: dict[str, Any]) -> list[tuple[list[Any], int]]:
    """(content list, index) for every image part, oldest first."""
    key = "messages" if protocol == "chat_completions" else "input"
    found = []
    for item in request.get(key) or []:
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, list):
            for i, part in enumerate(content):
                if isinstance(part, dict) and part.get("type") in ("image_url", "input_image"):
                    found.append((content, i))
    return found


def _url(part: dict[str, Any]) -> str | None:
    url = part.get("image_url")
    if isinstance(url, dict):
        url = url.get("url")
    return url if isinstance(url, str) else None


def _with_url(part: dict[str, Any], url: str) -> dict[str, Any]:
    if isinstance(part.get("image_url"), dict):
        return {**part, "image_url": {**part["image_url"], "url": url}}
    return {**part, "image_url": url}


def downscale(url: str, max_side: int) -> str:
    """A data URL with its longest side cut to `max_side`, or the same URL when it's already small enough."""
    from PIL import Image

    head, _, data = url.partition(",")
    if not head.startswith("data:image/") or ";base64" not in head:
        return url
    img = Image.open(io.BytesIO(base64.b64decode(data)))
    if max(img.size) <= max_side:
        return url
    scale = max_side / max(img.size)
    fmt = img.format or "PNG"
    small = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, fmt)
    return f"{head},{base64.b64encode(buf.getvalue()).decode()}"


class ImagePolicy(Policy):
    name = "images"

    def __init__(self, max_side: int | None = None, keep_last: int | None = None):
        if max_side is not None and max_side < 16:
            raise ValueError("--image-max-side must be at least 16 pixels")
        if keep_last is not None and keep_last < 1:
            raise ValueError("--image-keep-last must be at least 1")
        self.max_side = max_side
        self.keep_last = keep_last

    def apply(self, protocol: Protocol, request: dict[str, Any], ctx: SessionContext) -> dict[str, Any]:
        request = copy.deepcopy(request)  # message items can be shared with the agent's own history
        state = ctx.state_for(self.name)
        resized: dict[str, str] = state.setdefault("resized", {})  # hash of the original to the resized URL
        parts = _images(protocol, request)
        drop = len(parts) - self.keep_last if self.keep_last is not None else 0
        for n, (content, i) in enumerate(parts):
            if n < drop:
                content[i] = {"type": "text" if protocol == "chat_completions" else "input_text", "text": DROPPED}
                state["dropped"] = state.get("dropped", 0) + 1
                continue
            url = _url(content[i])
            if self.max_side is None or not url:
                continue
            key = hashlib.sha256(url.encode()).hexdigest()
            if key not in resized:
                resized[key] = downscale(url, self.max_side)
            if resized[key] != url:
                content[i] = _with_url(content[i], resized[key])
        return request
