"""Journey: real provider reads an attached chart image.

The image is generated locally (no downloaded assets). The provider receives a
base64 PNG attachment; the reply must name the taller bar. This is real
multimodal transport evidence, not OCR of a text layer.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = REPO_ROOT / "scripts" / "record-v4-provider-journeys.py"
_spec = importlib.util.spec_from_file_location("record_v4_provider_journeys", _SOURCE)
_module = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)
Sidecar = _module.Sidecar
_free_port = _module._free_port
_request = _module._request

OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-multimodal-journey.json"


def _chart_png() -> bytes:
    image = Image.new("RGB", (720, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 20), "Queue throughput", fill="black")
    # Axis and two bars: Beta is visibly taller than Alpha.
    draw.line((70, 340, 670, 340), fill="black", width=3)
    draw.rectangle((150, 220, 260, 340), outline="black", width=3)
    draw.rectangle((420, 90, 530, 340), outline="black", width=3)
    draw.text((165, 350), "Alpha", fill="black")
    draw.text((435, 350), "Beta", fill="black")
    draw.text((165, 190), "30", fill="black")
    draw.text((435, 60), "70", fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def main() -> int:
    api_key = (os.getenv("TRAINER_TEST_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("TRAINER_TEST_API_KEY is required (env only)")
    base_url = (os.getenv("TRAINER_TEST_BASE_URL") or "https://linksub.fun").rstrip("/")
    model = os.getenv("TRAINER_TEST_VISION_MODEL") or "deepseek-v4.1-flash"
    provider = {
        "name": "LinkSub",
        "base_url": base_url,
        "model": model,
        "protocol": "openai_chat_completions_compatible",
        "api_key_ref": "ui_proxy:test",
        "capabilities": {"vision": True},
        "request_defaults": {"temperature": 0},
    }
    png = _chart_png()
    payload = {
        "id": "chart-1",
        "kind": "image",
        "mimeType": "image/png",
        "name": "queue-chart.png",
        "dataBase64": base64.b64encode(png).decode("ascii"),
    }
    report: dict = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "provider": {"base_url": base_url, "model": model},
        "image": {"kind": "synthetic bar chart", "bytes": len(png)},
        "journey": {},
        "assertions": {},
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-vision-") as tmp:
        sidecar = Sidecar(Path(tmp) / "data", _free_port())
        sidecar.start()
        try:
            port = sidecar.port
            status, session = _request(port, "POST", "/session/start", {
                "workspace_id": "v4-multimodal",
                "workspace_name": "multimodal",
            })
            if status != 200:
                raise RuntimeError(f"session/start failed: {status} {session}")
            status, response = _request(port, "POST", "/session/message", {
                "provider": provider,
                "api_key": api_key,
                "workspace_id": "v4-multimodal",
                "session_id": session["session_id"],
                "message": "看这张柱状图：哪个队列的吞吐更高？只回答柱子标签。",
                "response_language": "zh-CN",
                "attachments": [payload],
            }, timeout=300)
            if status != 200:
                raise RuntimeError(f"session/message failed: {status} {response}")
            reply = str((response.get("reply") or {}).get("content") or "")
            report["journey"] = {
                "status": "PASS" if "Beta" in reply and ("70" in reply or "更高" in reply) else "PARTIAL",
                "reply": reply[:1600],
                "reply_chars": len(reply),
            }
            report["assertions"]["vision_reply_identifies_beta"] = "Beta" in reply
            report["assertions"]["vision_reply_compares_values"] = "70" in reply or "更高" in reply
        finally:
            sidecar.stop()
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = all(bool(value) for value in report["assertions"].values())
    output = Path(os.getenv("TRAINER_VISION_OUTPUT") or OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
