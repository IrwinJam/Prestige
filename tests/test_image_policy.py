import base64
import copy
import io

import pytest

PIL = pytest.importorskip("PIL")

from harness.policies.base import SessionContext  # noqa: E402
from harness.sim import SimulatedAdapter  # noqa: E402
from PIL import Image  # noqa: E402

from prestige.gateway import GuardedSession  # noqa: E402
from prestige.image_policy import DROPPED, ImagePolicy, downscale  # noqa: E402


def png(w: int, h: int, color=(200, 80, 40)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def size(url: str) -> tuple[int, int]:
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size


def chat(*urls: str) -> dict:
    return {
        "model": "m",
        "messages": [{"role": "user", "content": [{"type": "text", "text": f"frame {i}"}, {"type": "image_url", "image_url": {"url": u}}]} for i, u in enumerate(urls)],
    }


def test_downscale_keeps_aspect_and_format():
    small = downscale(png(1024, 768), 512)
    assert size(small) == (512, 384)
    assert small.startswith("data:image/png;base64,")
    already = png(300, 200)
    assert downscale(already, 512) == already


def test_same_image_resizes_to_the_same_bytes():
    url = png(1024, 768)
    assert downscale(url, 512) == downscale(url, 512)


def test_keep_last_trims_the_oldest_and_leaves_the_agent_request_alone():
    req = chat(png(64, 64), png(64, 64, (1, 2, 3)), png(64, 64, (9, 9, 9)))
    before = copy.deepcopy(req)
    out = ImagePolicy(keep_last=2).apply("chat_completions", req, SessionContext("t"))
    assert out["messages"][0]["content"][1] == {"type": "text", "text": DROPPED}
    assert out["messages"][1]["content"][1]["type"] == "image_url"
    assert req == before


def test_responses_format_and_remote_urls():
    req = {"input": [{"role": "user", "content": [{"type": "input_image", "image_url": png(800, 800)}, {"type": "input_image", "image_url": "https://example.test/a.png"}]}]}
    out = ImagePolicy(max_side=200).apply("responses", req, SessionContext("t"))
    parts = out["input"][0]["content"]
    assert size(parts[0]["image_url"]) == (200, 200)
    assert parts[1]["image_url"] == "https://example.test/a.png"


def test_the_model_gets_the_small_image_through_the_gateway():
    seen = []

    def model(protocol, request):
        seen.append(request)
        return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}

    s = GuardedSession(SimulatedAdapter(model), policies=[ImagePolicy(max_side=256, keep_last=1)], task_id="t")
    s.call("chat_completions", chat(png(1024, 768), png(1024, 768, (5, 5, 5))))
    parts = [m["content"][1] for m in seen[0]["messages"]]
    assert parts[0] == {"type": "text", "text": DROPPED}
    assert size(parts[1]["image_url"]["url"]) == (256, 192)


def test_bad_settings_are_refused():
    with pytest.raises(ValueError):
        ImagePolicy(max_side=4)
    with pytest.raises(ValueError):
        ImagePolicy(keep_last=0)
