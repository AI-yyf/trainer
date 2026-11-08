"""Journey 18: two independent clients, one formal plan revision.

Two sessions act like two windows sharing a workspace. Both start from the same
plan revision and try to save a formal title change concurrently; exactly one
advance may win, the other must get a 409 plan_revision_conflict. The plan is
generated with the real provider, so this is P + S evidence, not a browser
fixture.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
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

OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-dual-window-journey.json"


def main() -> int:
    api_key = (os.getenv("TRAINER_TEST_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("TRAINER_TEST_API_KEY is required (env only)")
    base_url = (os.getenv("TRAINER_TEST_BASE_URL") or "https://linksub.fun").rstrip("/")
    model = os.getenv("TRAINER_TEST_MODEL") or "deepseek-v4.1-flash"
    provider = {
        "name": "LinkSub",
        "base_url": base_url,
        "model": model,
        "protocol": "openai_chat_completions_compatible",
        "api_key_ref": "ui_proxy:test",
        "request_defaults": {"temperature": 0},
    }
    report: dict = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "provider": {"base_url": base_url, "model": model},
        "journey": {},
        "assertions": {},
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-dual-") as tmp:
        sidecar = Sidecar(Path(tmp) / "data", _free_port())
        sidecar.start()
        try:
            port = sidecar.port
            workspace_id = "v4-dual-window"
            first = _request(port, "POST", "/session/start", {"workspace_id": workspace_id, "workspace_name": "dual-a"})
            second = _request(port, "POST", "/session/start", {"workspace_id": workspace_id, "workspace_name": "dual-b"})
            if first[0] != 200 or second[0] != 200:
                raise RuntimeError("session/start failed for a dual client")
            session_a = first[1]["session_id"]
            session_b = second[1]["session_id"]
            status, last_test = _request(port, "POST", "/provider/test", {
                "provider": provider,
                "api_key": api_key,
                "response_language": "zh-CN",
                "probe_message": "Reply OK.",
            }, timeout=180)
            if status != 200:
                raise RuntimeError(f"provider test failed: {status} {last_test}")
            status, plan = _request(port, "POST", "/plan/generate", {
                "workspace_id": workspace_id,
                "session_id": session_a,
                "provider": provider,
                "api_key": api_key,
                "last_test_result": last_test,
                "response_language": "zh-CN",
                "profile": {
                    "long_term_goal": "learn Python concurrency",
                    "long_term_goals": ["learn Python concurrency"],
                    "background": "",
                    "weekly_hours": 4,
                    "teaching_style": "auto",
                    "answer_policy": "auto",
                    "preferred_libraries": [],
                },
                "goals": ["learn Python locks in two weeks"],
                "constraints": ["20 minutes a day"],
            }, timeout=300)
            if status != 200:
                raise RuntimeError(f"plan/generate failed: {status} {plan}")
            plan_id = str(plan.get("id") or "")
            revision = int(plan.get("_plan_revision") or 1)

            def update(title: str, session_id: str) -> tuple[int, dict]:
                return _request(port, "POST", "/plan/update", {
                    "plan_id": plan_id,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "title": title,
                    "formal_plan_mutation": True,
                    "expected_revision": revision,
                    "provider": provider,
                    "api_key": api_key,
                    "response_language": "zh-CN",
                })

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda args: update(*args), [
                    ("Dual window A wins", session_a),
                    ("Dual window B wins", session_b),
                ]))
            statuses = sorted(status for status, _ in results)
            result_details = [{"status": status, "payload": payload} for status, payload in results]
            winner_payload = next((payload for status, payload in results if status == 200), {})
            winner_plan = winner_payload.get("plan") if isinstance(winner_payload.get("plan"), dict) else {}
            winner_title = str(winner_plan.get("title") or winner_payload.get("title") or "")
            conflict_payload = next((payload for status, payload in results if status == 409), {})
            conflict_detail = conflict_payload.get("detail") if isinstance(conflict_payload.get("detail"), dict) else {}
            snapshot = _request(port, "GET", f"/memory/summary?workspace_id={workspace_id}")[1]
            current_plan = snapshot.get("plan") if isinstance(snapshot.get("plan"), dict) else {}
            report["journey"] = {
                "plan_id": plan_id,
                "start_revision": revision,
                "statuses": statuses,
                "winner_title": winner_title or current_plan.get("title"),
                "conflict_code": conflict_detail.get("code"),
                "current_title": current_plan.get("title"),
                "current_revision": current_plan.get("_plan_revision"),
                "session_a": session_a,
                "session_b": session_b,
                "results": result_details,
            }
            report["assertions"]["exactly_one_write"] = statuses == [200, 409]
            report["assertions"]["loser_reports_conflict"] = conflict_detail.get("code") == "plan_revision_conflict"
            report["assertions"]["stored_title_is_winner"] = (
                bool(winner_title) and current_plan.get("title") == winner_title
            )
            report["assertions"]["revision_advanced_once"] = int(current_plan.get("_plan_revision") or 0) == revision + 1
        finally:
            sidecar.stop()
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = all(bool(value) for value in report["assertions"].values())
    output = Path(os.getenv("TRAINER_DUAL_OUTPUT") or OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
