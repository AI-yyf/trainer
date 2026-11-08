"""Journey 10: real FSRS interval growth + delayed recall with a real provider.

A guided-pack card gives a deterministic, verifiable training card without
depending on the model to author JSON. The real provider is still used for the
connection test and the delayed-recall turn. TRAINER_TEST_NOW advances the
clock across the first 10-minute review and two later due dates.
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

OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-fsrs-delayed-recall.json"
DAY_0 = "2026-11-01T09:00:00Z"
DAY_1 = "2026-11-02T09:00:00Z"
DAY_4 = "2026-11-05T09:00:00Z"


def _verification_content(workspace: str) -> str:
  return f'''"""Remote identity: local VS Code window.
Workspace path: {workspace}.
Credential decision: the API key stays local; remote files are read through the companion.
This fact locks the next card: remote identity and workspace path.

Run with python. pytest output: 1 passed.
"""
RUNNER = "python"
TEST_RUNNER = "pytest"


def detectRemoteWorkspaceType(uri):
    return "ssh-remote"


def getRecommendedCredentialMode(workspace_type):
    return "local"


def isCredentialModeSecureForWorkspace(mode, workspace_type):
    return mode == "local"


def main():
    print(detectRemoteWorkspaceType("vscode-remote://ssh-remote+host/project"))
    print(getRecommendedCredentialMode("remote"))
    print(isCredentialModeSecureForWorkspace("local", "remote"))


if __name__ == "__main__":
    main()
'''


def _fsrs_state(snapshot: dict) -> dict:
    memory = snapshot.get("memory") if isinstance(snapshot.get("memory"), dict) else {}
    workspace = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    states = workspace.get("latest_training_fsrs_states") or workspace.get("latestTrainingFsrsStates")
    return states if isinstance(states, dict) else {}


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
        "clock": {"day0": DAY_0, "day1": DAY_1, "day4": DAY_4},
        "reviews": [],
        "delayed_recall": {},
        "assertions": {},
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-fsrs-") as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        port = _free_port()
        workspace_id = "v4-fsrs-delayed"
        project = root / "workspace"
        project.mkdir()
        card_id = ""
        session_id = ""
        content = _verification_content(str(project))
        source = project / "answer.py"

        def start(now_value: str) -> tuple[Sidecar, str]:
            os.environ["TRAINER_TEST_NOW"] = now_value
            sidecar = Sidecar(data_dir, port)
            sidecar.start()
            status, session = _request(port, "POST", "/session/start", {
                "workspace_id": workspace_id,
                "workspace_name": "FSRS delayed recall",
            })
            if status != 200:
                raise RuntimeError(f"session/start failed: {status} {session}")
            return sidecar, str(session["session_id"])

        def evaluate() -> dict:
            nonlocal card_id, session_id
            status, card = _request(port, "POST", "/training/card-status", {
                "workspace_id": workspace_id,
                "card_id": card_id,
                "new_status": "active",
                "reason": "fsrs verification",
            })
            if status != 200 and "active to active" not in str(card.get("detail") or ""):
                raise RuntimeError(f"card-status failed: {status} {card}")
            source.write_text(content, encoding="utf-8")
            (project / "test_answer.py").write_text(
                'from answer import main, detectRemoteWorkspaceType\n\n'
                'def test_main():\n'
                '    assert main() is None\n'
                '    assert detectRemoteWorkspaceType("x") == "ssh-remote"\n',
                encoding="utf-8",
            )
            status, result = _request(port, "POST", "/evaluate/current-file", {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "file_path": str(source),
                "language_id": "python",
                "content": content,
                "evaluation_source": "training",
                "training_card_id": card_id,
                "training_card_title": "练习：验证远程工作区边界",
                "training_phase": "verify",
                "acceptance_criteria": [
                    "定义 `main` 入口并通过 `python` 运行提交的内容",
                    "使用 `pytest` 或 `python` 运行一次并保留输出",
                    "运行时无 `SyntaxError` 或 `RuntimeError`",
                ],
                "learner_deliverables": [
                    "请提供远程身份与当前工作区路径或文件路径。",
                    "说明哪条提供的事实将锁定下一张卡。",
                ],
                "expected_symbols": [
                    "detectRemoteWorkspaceType",
                    "getRecommendedCredentialMode",
                    "isCredentialModeSecureForWorkspace",
                ],
            }, timeout=300)
            if status != 200:
                raise RuntimeError(f"evaluate/current-file failed: {status} {result}")
            snapshot = _request(port, "GET", f"/memory/summary?workspace_id={workspace_id}")[1]
            state = _fsrs_state(snapshot).get(card_id, {})
            report["reviews"].append({
                "now": os.environ.get("TRAINER_TEST_NOW"),
                "passed": bool(result.get("passed")),
                "summary": result.get("summary"),
                "interval": state.get("interval"),
                "due": state.get("due"),
                "stability": state.get("stability"),
                "reps": state.get("reps"),
                "lapses": state.get("lapses"),
            })
            return state

        # Day 0: generate the guided card and record the first Good review.
        sidecar, session_id = start(DAY_0)
        try:
            status, last_test = _request(port, "POST", "/provider/test", {
                "provider": provider,
                "api_key": api_key,
                "response_language": "zh-CN",
                "probe_message": "Reply OK.",
            }, timeout=180)
            if status != 200:
                raise RuntimeError(f"provider test failed: {status} {last_test}")
            status, generated = _request(port, "POST", "/training/generate-card", {
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "context_hint": "remote ssh workspace boundary",
                "target_skill": "remote workspace boundary",
                "focus_area": "Remote SSH",
                "provider": provider,
                "api_key": api_key,
                "last_test_result": last_test,
                "response_language": "zh-CN",
            }, timeout=120)
            if status != 200:
                raise RuntimeError(f"generate-card failed: {status} {generated}")
            card_id = str(generated["card"]["card_id"])
            first = evaluate()
        finally:
            sidecar.stop()

        # Advance to each FSRS due time until the card reaches a day-scale
        # interval (py-fsrs uses minute learning steps before graduation).
        current_state = first
        for _ in range(5):
            due = str(current_state.get("due") or "")
            if not due or int(current_state.get("interval") or 0) >= 1:
                break
            sidecar, session_id = start(due)
            try:
                current_state = evaluate()
            finally:
                sidecar.stop()

        # Delayed recall at the final due date, with the real provider.
        final_due = str(current_state.get("due") or DAY_4)
        sidecar, session_id = start(final_due)
        try:
            request = {
                "provider": provider,
                "api_key": api_key,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "message": "我隔了几天才回来。请只问我一个最小问题，检查我还记不记得远程工作区的边界。",
                "intent": "coach",
            }
            status, payload = _request(port, "POST", "/session/message", request, timeout=300)
            reply = str((payload.get("reply") or {}).get("content") or "") if status == 200 else ""
            report["delayed_recall"] = {
                "status": status,
                "reply": reply[:1600],
                "reply_chars": len(reply),
                "at_due": final_due,
                "detail": payload.get("detail") if status != 200 else None,
            }
        finally:
            sidecar.stop()

    intervals = [int(item.get("interval") or 0) for item in report["reviews"]]
    report["assertions"]["first_review_passed"] = bool(report["reviews"][0].get("passed"))
    report["assertions"]["first_due_is_ten_minutes"] = (
        str(report["reviews"][0].get("due") or "").startswith("2026-11-01T09:10")
    )
    report["assertions"]["all_reviews_passed"] = all(bool(item.get("passed")) for item in report["reviews"])
    report["assertions"]["reaches_day_interval"] = bool(intervals and intervals[-1] >= 1)
    report["assertions"]["delayed_recall_nonempty"] = report["delayed_recall"].get("reply_chars", 0) > 30
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = all(bool(value) for value in report["assertions"].values())
    output = Path(os.getenv("TRAINER_FSRS_OUTPUT") or OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
