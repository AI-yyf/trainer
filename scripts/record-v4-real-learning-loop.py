"""Real-provider, real-sidecar learning loop evidence.

Stages:
chat → explicit goal → teaching turn → generated practice card → real
pytest verification → LearnerState/memory update → restart → delayed review
turn with the real provider.

The key is read only from TRAINER_TEST_API_KEY and never written to the
report. Provider output is recorded verbatim (bounded) so the report is
evidence, not a claim.
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

OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-real-learning-loop.json"
DAY_0 = "2026-11-01T09:00:00Z"


def _state(memory: dict) -> dict:
    workspace = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    states = workspace.get("latest_training_fsrs_states") or workspace.get("latestTrainingFsrsStates")
    return states if isinstance(states, dict) else {}


def _reply(payload: dict) -> str:
    return str((payload.get("reply") or {}).get("content") or "")


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
    flat_provider = provider["provider"]
    report: dict = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "provider": {"base_url": base_url, "model": model},
        "clock": {"day0": DAY_0},
        "stages": {},
        "assertions": {},
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-loop-") as tmp:
        root = Path(tmp)
        workspace_id = "v4-real-learning-loop"
        project = root / "project"
        project.mkdir()
        source = project / "answer.py"
        content = """RUNNER = "python"
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
"""
        source.write_text(content, encoding="utf-8")
        test_file = project / "test_answer.py"
        test_file.write_text(
            "from answer import main, detectRemoteWorkspaceType\n\n"
            "def test_main():\n"
            "    assert main() is None\n"
            "    assert detectRemoteWorkspaceType('x') == 'ssh-remote'\n",
            encoding="utf-8",
        )
        data_dir = root / "data"
        port = _free_port()
        card_id = ""
        session_id = ""
        fsrs_state: dict = {}

        os.environ["TRAINER_TEST_NOW"] = DAY_0
        sidecar = Sidecar(data_dir, port)
        sidecar.start()
        try:
            status, test = _request(
                port,
                "POST",
                "/provider/test",
                {"provider": flat_provider, "api_key": api_key, "response_language": "zh-CN", "probe_message": "Reply OK."},
                timeout=180,
            )
            report["stages"]["provider_test"] = {"status": status, "ok": status == 200}
            if status != 200:
                raise RuntimeError(f"provider test failed: {status} {test}")

            status, start_payload = _request(
                port,
                "POST",
                "/session/start",
                {"workspace_id": workspace_id, "workspace_name": "Real learning loop"},
            )
            session_id = str(start_payload["session_id"])

            status, chat = _request(
                port,
                "POST",
                "/session/message",
                {
                    **provider,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "message": "我先不进入练习，只想聊聊 VS Code 远程工作区里凭证和文件边界到底怎么划。",
                },
                timeout=300,
            )
            chat_text = _reply(chat)
            report["stages"]["chat"] = {
                "status": status,
                "reply": chat_text[:1200],
                "reply_chars": len(chat_text),
            }

            status, goal = _request(
                port,
                "POST",
                "/goal/action",
                {
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "action": "start",
                    "title": "系统掌握 VS Code 远程工作区边界",
                },
            )
            report["stages"]["goal"] = {
                "status": status,
                "goal_id": (goal.get("goal") or {}).get("goalId"),
                "title": (goal.get("goal") or {}).get("title"),
            }

            status, teaching = _request(
                port,
                "POST",
                "/turn",
                {
                    **provider,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "message": "基于当前目标，先讲清远程工作区的凭证与文件边界，再给我一个最小练习。",
                    "intent": "coach",
                },
                timeout=300,
            )
            teaching_text = _reply(teaching)
            report["stages"]["teaching"] = {
                "status": status,
                "reply": teaching_text[:1600],
                "reply_chars": len(teaching_text),
            }

            status = 0
            generated: dict = {}
            card: dict = {}
            card_id = ""
            for _attempt in range(3):
                status, generated = _request(
                    port,
                    "POST",
                    "/training/generate-card",
                    {
                        "workspace_id": workspace_id,
                        "source": "conversation_gap",
                        "card_type": "practice",
                        "context_hint": (
                            "remote ssh workspace boundary"
                        ),
                        "target_skill": "remote workspace boundary",
                        "focus_area": "Remote SSH",
                        "provider": flat_provider,
                        "api_key": api_key,
                        "last_test_result": test,
                        "response_language": "zh-CN",
                        "current_file_path": str(source),
                        "current_file_language_id": "python",
                        "current_file_content": content,
                        "workspace_root_path": str(project),
                    },
                    timeout=300,
                )
                card = generated.get("card") if isinstance(generated.get("card"), dict) else {}
                card_id = str(card.get("card_id") or "")
                if status == 200 and card_id:
                    break
                time.sleep(1)
            report["stages"]["practice"] = {
                "status": status,
                "card_id": card_id,
                "title": card.get("title"),
                "learning_subtype": card.get("learning_subtype"),
            }
            if status != 200 or not card_id:
                raise RuntimeError(f"generate-card failed: {status} {generated}")

            _request(
                port,
                "POST",
                "/training/card-status",
                {
                    "workspace_id": workspace_id,
                    "card_id": card_id,
                    "new_status": "active",
                    "reason": "real learning loop verification",
                },
            )
            status, evaluation = _request(
                port,
                "POST",
                "/evaluate/current-file",
                {
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "file_path": str(source),
                    "language_id": "python",
                    "content": content,
                    "evaluation_source": "training",
                    "training_card_id": card_id,
                    "training_card_title": str(card.get("title") or "Remote workspace boundary"),
                    "training_phase": "verify",
                    "acceptance_criteria": [
                        "定义 main 入口并通过 python 运行提交的内容",
                        "使用 pytest 运行一次并保留输出",
                    ],
                    "learner_deliverables": ["提交可运行的 answer.py"],
                    "expected_symbols": [
                        "detectRemoteWorkspaceType",
                        "getRecommendedCredentialMode",
                        "isCredentialModeSecureForWorkspace",
                    ],
                },
                timeout=300,
            )
            report["stages"]["verify"] = {
                "status": status,
                "passed": bool(evaluation.get("passed")),
                "summary": evaluation.get("summary"),
                "dynamic_checks": [
                    {"id": item.get("id"), "status": item.get("status")}
                    for item in evaluation.get("dynamic_checks", [])
                    if isinstance(item, dict)
                ],
            }

            _, learner = _request(
                port, "GET", f"/learner/state?workspace_id={workspace_id}"
            )
            evidence = learner.get("evidence") if isinstance(learner.get("evidence"), dict) else {}
            mastery = learner.get("mastery") if isinstance(learner.get("mastery"), dict) else {}
            report["stages"]["memory_update"] = {
                "evidence_total": evidence.get("total"),
                "evidence_confidence": evidence.get("confidence"),
                "mastery_dimensions": {
                    key: value.get("state") if isinstance(value, dict) else value
                    for key, value in (mastery.get("dimensions") or {}).items()
                },
                "goal": (learner.get("goal") or {}).get("confidence"),
            }

            _, memory = _request(port, "GET", f"/memory/summary?workspace_id={workspace_id}")
            states = _state(memory.get("memory") or {})
            fsrs_state = states.get(card_id, {}) if isinstance(states, dict) else {}
            report["stages"]["fsrs"] = {
                "interval": fsrs_state.get("interval"),
                "due": fsrs_state.get("due"),
                "state": fsrs_state.get("state"),
                "reps": fsrs_state.get("reps"),
            }
        finally:
            sidecar.stop()

        # Return after the scheduled interval, restart the same sidecar data.
        due = str(fsrs_state.get("due") or "")
        if not due:
            report["stages"]["delayed_review"] = {"status": 0, "error": "no fsrs due"}
        else:
            os.environ["TRAINER_TEST_NOW"] = due
            sidecar = Sidecar(data_dir, port)
            sidecar.start()
            try:
                _, session = _request(
                    port,
                    "POST",
                    "/session/start",
                    {"workspace_id": workspace_id, "workspace_name": "Real learning loop"},
                )
                session_id = str(session["session_id"])
                status, delayed = _request(
                    port,
                    "POST",
                    "/session/message",
                    {
                        **provider,
                        "workspace_id": workspace_id,
                        "session_id": session_id,
                        "message": "我隔了一段时间回来。先问我一个最小问题，检查我还记不记得远程工作区的边界。",
                    },
                    timeout=300,
                )
                delayed_text = _reply(delayed)
                _, learner_after = _request(
                    port, "GET", f"/learner/state?workspace_id={workspace_id}"
                )
                _, goal_after = _request(
                    port, "GET", f"/goal/current?workspace_id={workspace_id}"
                )
                report["stages"]["delayed_review"] = {
                    "status": status,
                    "at": due,
                    "reply": delayed_text[:1600],
                    "reply_chars": len(delayed_text),
                    "goal_active": (goal_after.get("goal") or {}).get("status"),
                    "evidence_total": (learner_after.get("evidence") or {}).get("total"),
                }
            finally:
                sidecar.stop()

    chat_reply = report["stages"].get("chat", {})
    tea = report["stages"].get("teaching", {})
    verify = report["stages"].get("verify", {})
    memory_update = report["stages"].get("memory_update", {})
    delayed = report["stages"].get("delayed_review", {})
    report["assertions"] = {
        "chat_reply_nonempty": chat_reply.get("reply_chars", 0) > 30,
        "goal_started": bool(report["stages"].get("goal", {}).get("goal_id")),
        "teaching_reply_nonempty": tea.get("reply_chars", 0) > 30,
        "practice_card_generated": bool(report["stages"].get("practice", {}).get("card_id")),
        "verification_passed": bool(verify.get("passed")),
        "memory_evidence_updated": int(memory_update.get("evidence_total") or 0) > 0,
        "delayed_reply_nonempty": delayed.get("reply_chars", 0) > 30,
        "goal_survived_restart": delayed.get("goal_active") == "active",
    }
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = all(bool(value) for value in report["assertions"].values())
    output = Path(os.getenv("TRAINER_LOOP_OUTPUT") or OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
