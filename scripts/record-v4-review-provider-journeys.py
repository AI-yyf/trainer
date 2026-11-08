"""Record V4 journeys 9/11/12 with a day clock and the real provider.

Day 0 writes repeated-error learning signals; the sidecar restarts on a later
TRAINER_TEST_NOW date so the review queue becomes due. The coach turn then uses
the real provider. Journey 10 still needs an FSRS card interval path and is
reported separately as NOT_EXECUTED.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = REPO_ROOT / "scripts" / "record-v4-provider-journeys.py"
_spec = importlib.util.spec_from_file_location("record_v4_provider_journeys", _SOURCE)
_module = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)
Sidecar = _module.Sidecar
_free_port = _module._free_port
_request = _module._request

OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-review-provider-journeys.json"


def main() -> int:
    api_key = (os.getenv("TRAINER_TEST_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("TRAINER_TEST_API_KEY is required (env only)")
    base_url = (os.getenv("TRAINER_TEST_BASE_URL") or "https://linksub.fun").rstrip("/")
    model = os.getenv("TRAINER_TEST_MODEL") or "deepseek-v4.1-flash"
    provider = {
        "provider": {
            "name": "LinkSub",
            "base_url": base_url,
            "model": model,
            "protocol": "openai_chat_completions_compatible",
            "api_key_ref": "ui_proxy:test",
            "request_defaults": {"temperature": 0},
        },
        "api_key": api_key,
        "response_language": "zh-CN",
        "use_agent_loop": False,
    }
    report: dict = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "provider": {"base_url": base_url, "model": model},
        "clock": {"day0": "2026-11-01T09:00:00Z", "day3": "2026-11-04T09:00:00Z", "day30": "2026-12-01T09:00:00Z"},
        "journeys": {},
        "assertions": {},
        "not_executed": {
            "10_delayed_recall": {
                "title": "正确延迟回忆，间隔延长",
                "note": "The weakness/review path clears in 10 minutes; a real FSRS card interval needs card generation, which this run did not produce.",
            }
        },
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-review-") as tmp:
        data_dir = Path(tmp) / "data"
        port = _free_port()
        workspace_id = "v4-review-provider"
        concepts = ["tuple mutability", "dict key hashing", "list aliasing", "closure capture", "iterator exhaustion"]

        os.environ["TRAINER_TEST_NOW"] = "2026-11-01T09:00:00Z"
        sidecar = Sidecar(data_dir, port)
        sidecar.start()
        try:
            status, session = _request(port, "POST", "/session/start", {"workspace_id": workspace_id, "workspace_name": "review"})
            if status != 200:
                raise RuntimeError(f"session/start failed: {status} {session}")
            session_id = session["session_id"]
            for index in range(10):
                concept = concepts[index % len(concepts)]
                _request(port, "POST", "/learning/signal", {
                    "workspace_id": workspace_id,
                    "concepts": [concept],
                    "outcome": "repeated_error",
                    "summary": f"day0 failure record {index}",
                    "focus_area": "Python fundamentals",
                })
        finally:
            sidecar.stop()

        # Day 3: due queue is live. Ask the real model to run a review.
        os.environ["TRAINER_TEST_NOW"] = "2026-11-04T09:00:00Z"
        sidecar = Sidecar(data_dir, port)
        sidecar.start()
        try:
            snapshot = _request(port, "GET", f"/memory/summary?workspace_id={workspace_id}")[1]
            memory = snapshot.get("memory") if isinstance(snapshot.get("memory"), dict) else {}
            due_reviews = memory.get("due_reviews") if isinstance(memory.get("due_reviews"), list) else []
            due_count = int(memory.get("due_review_count") or 0)
            due_concepts = [str(item.get("concept") or "") for item in due_reviews if isinstance(item, dict)]
            _, reply = _request(port, "POST", "/session/message", {
                **provider,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "message": "今天只复习 tuple mutability。先问我一个最小问题，不要一次讲完。",
            })
            reply_text = str((reply.get("reply") or {}).get("content") or "")
            report["journeys"]["9_forgetting_days"] = {
                "status": "PASS" if due_count > 0 and len(reply_text) > 30 else "PARTIAL",
                "due_count": due_count,
                "due_concepts": due_concepts[:10],
                "reply": reply_text[:1600],
                "reply_chars": len(reply_text),
            }
            report["assertions"]["review_queue_due_after_days"] = due_count > 0
            report["assertions"]["review_turn_nonempty"] = len(reply_text) > 30

            # Journey 11: dismissing a review must not leave the same item due.
            dismiss_concept = next((concept for concept in concepts if concept in due_concepts), "list aliasing")
            status, action = _request(port, "POST", "/training/review-queue/action", {
                "workspace_id": workspace_id,
                "concept": dismiss_concept,
                "action": "skip",
                "note": "busy; review later",
            })
            after = _request(port, "GET", f"/memory/summary?workspace_id={workspace_id}")[1]
            after_memory = after.get("memory") if isinstance(after.get("memory"), dict) else {}
            after_due = after_memory.get("due_reviews") if isinstance(after_memory.get("due_reviews"), list) else []
            after_concepts = [str(item.get("concept") or "") for item in after_due if isinstance(item, dict)]
            action_payload = action.get("actions") if isinstance(action.get("actions"), list) else []
            next_review = str(action_payload[0].get("next_review_at") or "") if action_payload else ""
            _, busy_reply = _request(port, "POST", "/session/message", {
                **provider,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "message": "我现在很忙，先别安排复习；只用一句话提醒我 tuple 为什么不可变。",
            })
            busy_text = str((busy_reply.get("reply") or {}).get("content") or "")
            report["journeys"]["11_refuse_review"] = {
                "status": "PASS" if status == 200 and dismiss_concept not in after_concepts and len(busy_text) > 20 else "PARTIAL",
                "dismissed_concept": dismiss_concept,
                "action": action_payload[0] if action_payload else None,
                "due_concepts_after": after_concepts[:10],
                "next_review_at": next_review,
                "reply": busy_text[:1200],
            }
            report["assertions"]["dismissed_review_not_due_same_day"] = dismiss_concept not in after_concepts
            report["assertions"]["busy_turn_nonempty"] = len(busy_text) > 20
        finally:
            sidecar.stop()

        # Journey 12: after a long absence, the queue stays bounded and unique.
        os.environ["TRAINER_TEST_NOW"] = "2026-12-01T09:00:00Z"
        sidecar = Sidecar(data_dir, port)
        sidecar.start()
        try:
            snapshot = _request(port, "GET", f"/memory/summary?workspace_id={workspace_id}")[1]
            memory = snapshot.get("memory") if isinstance(snapshot.get("memory"), dict) else {}
            due_reviews = memory.get("due_reviews") if isinstance(memory.get("due_reviews"), list) else []
            due_concepts = [str(item.get("concept") or "") for item in due_reviews if isinstance(item, dict)]
            _, reply = _request(port, "POST", "/session/message", {
                **provider,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "message": "我隔了很久才回来，今天只做最小复习。先给我一个最小回顾问题。",
            })
            reply_text = str((reply.get("reply") or {}).get("content") or "")
            report["journeys"]["12_long_absence"] = {
                "status": "PASS" if len(due_concepts) == len(set(due_concepts)) and len(reply_text) > 30 else "PARTIAL",
                "due_count": len(due_concepts),
                "unique_due_count": len(set(due_concepts)),
                "due_concepts": due_concepts[:20],
                "reply": reply_text[:1600],
            }
            report["assertions"]["long_absence_no_duplicate_reviews"] = len(due_concepts) == len(set(due_concepts))
            report["assertions"]["long_absence_reply_nonempty"] = len(reply_text) > 30
        finally:
            sidecar.stop()
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = all(bool(value) for value in report["assertions"].values())
    output = Path(os.getenv("TRAINER_REVIEW_OUTPUT") or OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
