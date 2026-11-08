"""Record V4 journeys 2 and 3 against a real provider.

Journey 2: an ordinary question must not create a Goal/plan/card.
Journey 3: an explicit capability statement must create a persisted Goal, and
the Goal must survive a real sidecar restart and remain attached to the next
continuation turn.

The API key is read from ``TRAINER_TEST_API_KEY`` (or
``TRAINER_PROVIDER_SMOKE_API_KEY``) and never written to the report.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPO_ROOT / "server"
DEFAULT_BASE_URL = "https://linksub.fun"
DEFAULT_MODEL = "minimax-m3"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-journey-2-3-goal-real.json"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    port: int,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    timeout: float = 300.0,
) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc


class Sidecar:
    def __init__(self, data_dir: Path, port: int) -> None:
        self.data_dir = data_dir
        self.port = port
        self.process: subprocess.Popen[bytes] | None = None
        self.log_path = data_dir / "sidecar.log"

    def start(self) -> None:
        env = {
            **os.environ,
            "TRAINER_DATA_DIR": str(self.data_dir),
            "TRAINER_DB_NAME": "journey.db",
            "TRAINER_ENABLE_NETWORK_FETCH": "false",
        }
        log = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(SERVER_ROOT / "run_sidecar.py"),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=SERVER_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"sidecar exited early; see {self.log_path}")
            try:
                _request(self.port, "GET", "/health", timeout=3)
                return
            except (OSError, RuntimeError):
                time.sleep(0.5)
        raise RuntimeError(f"sidecar did not become healthy; see {self.log_path}")

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process = None


def _provider(api_key: str, base_url: str, model: str) -> dict:
    return {
        "provider": {
            "name": "LinkSub",
            "base_url": base_url,
            "model": model,
            "protocol": "openai_chat_completions_compatible",
            "api_key_ref": "ui_proxy:test",
        },
        "api_key": api_key,
        "response_language": "zh-CN",
        "use_agent_loop": False,
    }


def _message(port: int, *, session_id: str, workspace_id: str, text: str, provider: dict) -> dict:
    return _request(
        port,
        "POST",
        "/session/message",
        {
            **provider,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "message": text,
        },
    )


def main() -> int:
    api_key = (
        os.getenv("TRAINER_TEST_API_KEY")
        or os.getenv("TRAINER_PROVIDER_SMOKE_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise SystemExit("TRAINER_TEST_API_KEY is required (env only).")
    base_url = (os.getenv("TRAINER_TEST_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    model = os.getenv("TRAINER_TEST_MODEL") or DEFAULT_MODEL
    workspace_id = f"v4-goal-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    provider = _provider(api_key, base_url, model)
    report: dict = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "provider": {"base_url": base_url, "model": model},
        "workspace_id": workspace_id,
        "journeys": {},
        "assertions": {},
        "restart": {},
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-goal-") as tmp:
        data_dir = Path(tmp)
        port = _free_port()
        sidecar = Sidecar(data_dir, port)
        sidecar.start()
        try:
            session = _request(
                port,
                "POST",
                "/session/start",
                {"workspace_id": workspace_id, "workspace_name": "V4 Goal Journey"},
            )
            session_id = str(session.get("session_id") or "")
            if not session_id:
                raise RuntimeError("session/start returned no session_id")
            report["session_id"] = session_id

            # Journey 2 — ordinary question.
            casual_prompt = "PPO 是什么？请用两句话解释。"
            casual_started = time.monotonic()
            casual = _message(
                port,
                session_id=session_id,
                workspace_id=workspace_id,
                text=casual_prompt,
                provider=provider,
            )
            casual_reply = str((casual.get("reply") or {}).get("content") or "")
            goal_after_casual = _request(
                port, "GET", f"/goal/current?workspace_id={workspace_id}"
            ).get("goal")
            snapshot = casual.get("snapshot") or {}
            plan = snapshot.get("plan")
            memory = snapshot.get("memory") or {}
            report["journeys"]["2_casual_question"] = {
                "prompt": casual_prompt,
                "reply": casual_reply,
                "reply_chars": len(casual_reply),
                "elapsed_ms": int((time.monotonic() - casual_started) * 1000),
                "goal_after": goal_after_casual,
                "plan_after": plan,
                "task_after": snapshot.get("current_task"),
                "review_queue_summary": snapshot.get("review_queue_summary"),
                "active_training_card_routing": memory.get("active_training_card_routing"),
                "training_card_candidates": memory.get("training_card_candidates"),
            }
            if not casual_reply.strip():
                raise RuntimeError("journey 2: provider returned an empty reply")
            if goal_after_casual is not None:
                raise RuntimeError("journey 2: casual question created a Goal")
            if plan is not None:
                raise RuntimeError("journey 2: casual question created a plan")
            if memory.get("active_training_card_routing") is not None:
                raise RuntimeError("journey 2: casual question created a training card")
            report["assertions"]["journey2_no_goal"] = True
            report["assertions"]["journey2_no_plan"] = True
            report["assertions"]["journey2_no_training_card"] = True

            # Journey 3 — explicit capability goal.
            goal_prompt = "我想真正学会实现 PPO Clip，请先判断我该从哪里开始。"
            goal_started = time.monotonic()
            goal_turn = _message(
                port,
                session_id=session_id,
                workspace_id=workspace_id,
                text=goal_prompt,
                provider=provider,
            )
            goal_reply = str((goal_turn.get("reply") or {}).get("content") or "")
            goal_after = _request(
                port, "GET", f"/goal/current?workspace_id={workspace_id}"
            ).get("goal")
            if not goal_reply.strip():
                raise RuntimeError("journey 3: provider returned an empty reply")
            if not isinstance(goal_after, dict):
                raise RuntimeError("journey 3: explicit capability statement created no Goal")
            if goal_after.get("source") != "coach_detected":
                raise RuntimeError("journey 3: Goal source is not coach_detected")
            if "PPO Clip" not in str(goal_after.get("title") or ""):
                raise RuntimeError("journey 3: Goal title lost the capability")
            report["journeys"]["3_explicit_goal"] = {
                "prompt": goal_prompt,
                "reply": goal_reply,
                "reply_chars": len(goal_reply),
                "elapsed_ms": int((time.monotonic() - goal_started) * 1000),
                "goal_after": goal_after,
            }
            report["assertions"]["journey3_goal_created"] = True
            report["assertions"]["journey3_title_clean"] = True

            # Restart the real sidecar on the same data dir; Goal must survive.
            old_goal_id = str(goal_after.get("goalId") or "")
            sidecar.stop()
            sidecar.start()
            restored_session = _request(
                port,
                "POST",
                "/session/start",
                {"workspace_id": workspace_id, "workspace_name": "V4 Goal Journey"},
            )
            restored_session_id = str(restored_session.get("session_id") or "")
            restored_goal = _request(
                port, "GET", f"/goal/current?workspace_id={workspace_id}"
            ).get("goal")
            if not isinstance(restored_goal, dict):
                raise RuntimeError("journey 3: Goal did not survive sidecar restart")
            if str(restored_goal.get("goalId") or "") != old_goal_id:
                raise RuntimeError("journey 3: a different Goal came back after restart")
            report["restart"] = {
                "old_goal_id": old_goal_id,
                "restored_goal": restored_goal,
                "restored_session_id": restored_session_id,
            }
            report["assertions"]["journey3_goal_survives_restart"] = True

            continuation_prompt = "继续，从最小实现开始，先给我第一步。"
            continuation = _message(
                port,
                session_id=restored_session_id,
                workspace_id=workspace_id,
                text=continuation_prompt,
                provider=provider,
            )
            continuation_reply = str((continuation.get("reply") or {}).get("content") or "")
            goal_after_continuation = _request(
                port, "GET", f"/goal/current?workspace_id={workspace_id}"
            ).get("goal")
            if not continuation_reply.strip():
                raise RuntimeError("journey 3: continuation returned an empty reply")
            if str((goal_after_continuation or {}).get("goalId") or "") != old_goal_id:
                raise RuntimeError("journey 3: continuation detached from the Goal")
            report["journeys"]["3_continuation"] = {
                "prompt": continuation_prompt,
                "reply": continuation_reply,
                "reply_chars": len(continuation_reply),
                "goal_after": goal_after_continuation,
            }
            report["assertions"]["journey3_continuation_keeps_goal"] = True
        finally:
            sidecar.stop()
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = all(report["assertions"].values())
    output = Path(os.getenv("TRAINER_JOURNEY_OUTPUT") or DEFAULT_OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
PY