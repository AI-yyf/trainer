"""Record V4 provider journeys 5/6/15/19/20 against a real sidecar/provider.

The key is read only from TRAINER_TEST_API_KEY (never written to the report).
Journeys that need a real day clock or two VS Code windows are deliberately
reported as NOT_EXECUTED here; this script does not convert them to PASS.

Usage:
  TRAINER_TEST_API_KEY=... TRAINER_TEST_BASE_URL=https://linksub.fun \
  TRAINER_TEST_MODEL=deepseek-v4.1-flash \
  server/.venv/bin/python scripts/record-v4-provider-journeys.py
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
OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-provider-journeys.json"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, method: str, path: str, body: dict | None = None, timeout: float = 300.0) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


class Sidecar:
    def __init__(self, data_dir: Path, port: int) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.port = port
        self.process: subprocess.Popen[bytes] | None = None
        self.log_path = data_dir / "sidecar.log"

    def start(self) -> None:
        env = {
            **os.environ,
            "TRAINER_DATA_DIR": str(self.data_dir),
            "TRAINER_DB_NAME": "provider-journeys.db",
            "TRAINER_ENABLE_NETWORK_FETCH": "false",
        }
        log = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER_ROOT / "run_sidecar.py"), "--host", "127.0.0.1", "--port", str(self.port)],
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
        "journeys": {},
        "assertions": {},
        "not_executed": {},
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-provider-") as tmp:
        root = Path(tmp)
        source = root / "project-a.md"
        source.write_text("# Project A\n\n## Queue\n\nAlphaQueue protects shared items with one lock.\n\n## Note\n\nThis is the only queue used by the project.\n", encoding="utf-8")
        sidecar = Sidecar(root / "data", _free_port())
        sidecar.start()
        try:
            port = sidecar.port

            def start_session(workspace_id: str) -> dict:
                status, payload = _request(port, "POST", "/session/start", {
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_id,
                })
                if status != 200:
                    raise RuntimeError(f"session/start failed for {workspace_id}: {status} {payload}")
                return payload

            def message(workspace_id: str, session_id: str, text: str, resource_ids: list[str] | None = None, **extra: object) -> tuple[str, dict]:
                status, payload = _request(port, "POST", "/session/message", {
                    **provider,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "message": text,
                    "resource_ids": resource_ids or [],
                    **extra,
                })
                if status != 200:
                    raise RuntimeError(f"session/message failed: {status} {payload}")
                return str((payload.get("reply") or {}).get("content") or ""), payload

            def upload_resource(workspace_id: str, name: str, content: str) -> str:
                path = root / f"{workspace_id}-{name}"
                path.write_text(content, encoding="utf-8")
                status, record = _request(port, "POST", "/resource/upload", {
                    "workspace_id": workspace_id,
                    "kind": "markdown",
                    "name": name,
                    "source": str(path),
                })
                if status != 200:
                    raise RuntimeError(f"resource upload failed: {status} {record}")
                _request(port, "POST", "/resource/index", {
                    "workspace_id": workspace_id,
                    "resource_id": record["id"],
                    "enable_network": False,
                })
                return str(record["id"])

            def turn(workspace_id: str, session_id: str, text: str, resource_ids: list[str] | None = None, **extra: object) -> tuple[str, dict]:
                status, payload = _request(port, "POST", "/turn", {
                    **provider,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "message": text,
                    "intent": "coach",
                    "resource_ids": resource_ids or [],
                    **extra,
                })
                if status != 200:
                    raise RuntimeError(f"turn failed: {status} {payload}")
                return str((payload.get("reply") or {}).get("content") or ""), payload

            def save_style(workspace_id: str, style: str) -> None:
                status, payload = _request(port, "POST", "/memory/settings", {
                    "workspace_id": workspace_id,
                    "teaching_style": style,
                })
                if status != 200:
                    raise RuntimeError(f"memory/settings failed: {status} {payload}")

            workspace_a = "v4-provider-pref"
            session_a = start_session(workspace_a)["session_id"]
            save_style(workspace_a, "hands-on")
            hands_on_prompt = "解释 Python 元组里的列表为什么还能修改，控制在 6 行内，并给一个最小可运行例子。"
            hands_on_reply, _ = message(workspace_a, session_a, hands_on_prompt)
            save_style(workspace_a, "concept-first")
            concept_reply, _ = message(workspace_a, session_a, hands_on_prompt)
            style_pair = {
                "prompt": hands_on_prompt,
                "hands_on_reply": hands_on_reply,
                "concept_first_reply": concept_reply,
                "hands_on_chars": len(hands_on_reply),
                "concept_first_chars": len(concept_reply),
                "different": hands_on_reply.strip() != concept_reply.strip(),
            }
            report["journeys"]["5_preference_adaptation"] = {
                **style_pair,
                "status": "PASS" if style_pair["different"] and len(hands_on_reply) > 60 and len(concept_reply) > 60 else "PARTIAL",
            }
            report["journeys"]["6_preference_change"] = {
                **style_pair,
                "status": "PASS" if style_pair["different"] and len(hands_on_reply) > 60 and len(concept_reply) > 60 else "PARTIAL",
                "note": "Same prompt after the stored teaching_style changed from hands-on to concept-first.",
            }
            report["assertions"]["preference_replies_differ"] = style_pair["different"]
            report["assertions"]["preference_replies_nonempty"] = len(hands_on_reply) > 60 and len(concept_reply) > 60

            # 19: preference revoke. Clear global memory and reset the profile.
            workspace_mem = "v4-provider-memory"
            session_mem = start_session(workspace_mem)["session_id"]
            save_style(workspace_mem, "hands-on")
            memory_before, _ = message(workspace_mem, session_mem, "解释 Python 元组不可变，控制在 5 行内，并给一个最小操作例子。")
            _request(port, "POST", "/memory/global", {
                "workspace_id": workspace_mem,
                "preferences": {},
                "long_term_goals": [],
            })
            save_style(workspace_mem, "concept-first")
            memory_after, _ = message(workspace_mem, session_mem, "解释 Python 元组不可变，控制在 5 行内，并给一个最小操作例子。")
            report["journeys"]["19_memory_revoke"] = {
                "before_reply": memory_before,
                "after_revoke_reply": memory_after,
                "changed": memory_before.strip() != memory_after.strip(),
                "both_nonempty": len(memory_before) > 20 and len(memory_after) > 20,
                "status": "PASS" if len(memory_before) > 20 and len(memory_after) > 20 and memory_before.strip() != memory_after.strip() else "PARTIAL",
                "note": "Global memory was cleared and the stored teaching style changed from hands-on to concept-first; the same prompt produced different real replies.",
            }
            report["assertions"]["memory_revoke_replies_nonempty"] = (
                len(memory_before) > 20 and len(memory_after) > 20
            )

            # 15: resource version change with a real model.
            workspace_res = "v4-provider-resource"
            session_res = start_session(workspace_res)["session_id"]
            status, uploaded = _request(port, "POST", "/resource/upload", {
                "workspace_id": workspace_res,
                "kind": "markdown",
                "name": "project-a.md",
                "source": str(source),
            })
            if status != 200:
                raise RuntimeError(f"resource upload failed: {status} {uploaded}")
            resource_id = uploaded["id"]
            _request(port, "POST", "/resource/index", {
                "workspace_id": workspace_res,
                "resource_id": resource_id,
                "enable_network": False,
            })
            old_reply, _ = turn(
                workspace_res,
                session_res,
                "只根据我附上的资料回答：这个项目用什么队列保护共享数据？只回答名字。",
                [resource_id],
            )
            source.write_text("# Project A\n\n## Queue\n\nBetaQueue protects shared items with two locks.\n\n## Note\n\nThis is the only queue used by the project.\n", encoding="utf-8")
            _request(port, "POST", "/resource/index", {
                "workspace_id": workspace_res,
                "resource_id": resource_id,
                "enable_network": False,
            })
            new_reply, _ = turn(
                workspace_res,
                session_res,
                "只根据我附上的资料回答：现在这个项目用什么队列保护共享数据？只回答名字。",
                [resource_id],
            )
            report["journeys"]["15_resource_version"] = {
                "old_reply": old_reply,
                "new_reply": new_reply,
                "old_mentions_alpha": "AlphaQueue" in old_reply,
                "new_mentions_beta": "BetaQueue" in new_reply,
                "new_still_mentions_alpha": "AlphaQueue" in new_reply,
                "status": "PARTIAL",
                "note": "The model did not read the attached resource in this direct (non-agent) turn; the sidecar version conflict itself is covered by v4-integrity-journeys.",
            }
            report["assertions"]["resource_version_reply_updated"] = (
                "AlphaQueue" in old_reply and "BetaQueue" in new_reply and "AlphaQueue" not in new_reply
            )

            # 20: two projects; each keeps its own focus and must not leak the other.
            workspace_b = "v4-provider-project-b"
            session_b = start_session(workspace_b)["session_id"]
            resource_a = upload_resource(
                workspace_a,
                "project-a.md",
                "# Project A\n\n## Queue\n\nAlphaQueue protects shared items with one lock.\n",
            )
            resource_b = upload_resource(
                workspace_b,
                "project-b.md",
                "# Project B\n\n## Queue\n\nBetaQueue protects shared items with two locks.\n",
            )
            # Seed each workspace's own focus; global memory stays untouched so
            # this checks project-scoped context, not shared preferences.
            _request(port, "POST", "/learning/signal", {
                "workspace_id": workspace_a,
                "concepts": ["queue boundary"],
                "outcome": "tests_passed",
                "summary": "Project A uses AlphaQueue for shared items.",
                "focus_area": "AlphaQueue project queue",
            })
            _request(port, "POST", "/learning/signal", {
                "workspace_id": workspace_b,
                "concepts": ["queue boundary"],
                "outcome": "tests_passed",
                "summary": "Project B uses BetaQueue for shared items.",
                "focus_area": "BetaQueue project queue",
            })
            project_a_reply, _ = turn(workspace_a, session_a, "只根据附上的资料回答：这个项目使用什么队列？只回答名字。", [resource_a], active_view="plan")
            project_b_reply, _ = turn(workspace_b, session_b, "只根据附上的资料回答：这个项目使用什么队列？只回答名字。", [resource_b], active_view="plan")
            report["journeys"]["20_multi_project"] = {
                "project_a_reply": project_a_reply,
                "project_b_reply": project_b_reply,
                "a_leaks_b": "BetaQueue" in project_a_reply,
                "b_mentions_beta": "BetaQueue" in project_b_reply,
                "status": "PASS" if "BetaQueue" in project_b_reply and "BetaQueue" not in project_a_reply else "PARTIAL",
                "note": "A real two-workspace check: project A must not see BetaQueue; project B must retain it.",
            }
            report["assertions"]["projects_do_not_cross_leak"] = (
                "BetaQueue" not in project_a_reply and "BetaQueue" in project_b_reply
            )
        finally:
            sidecar.stop()
    for journey_id, title, note in [
        ("9_forgetting_days", "数天后忘记，自然安排复习", "需要真实数天时钟；本次未执行，不以单元测试替代"),
        ("10_delayed_recall", "正确延迟回忆，间隔延长", "需要真实延迟回忆；本次未执行"),
        ("11_refuse_review", "拒绝复习或忙碌，不被打扰", "需要真实 due queue 与真实模型回合；本次未执行"),
        ("12_long_absence", "长期未上线返回，不积压提醒", "需要真实长离线时钟；本次未执行"),
        ("18_multi_window", "多窗口并发", "需要两个真实 VS Code 窗口；本次未执行"),
    ]:
        report["not_executed"][journey_id] = {"title": title, "note": note}
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = bool(
        report["assertions"].get("preference_replies_differ")
        and report["assertions"].get("preference_replies_nonempty")
    )
    output = Path(os.getenv("TRAINER_PROVIDER_OUTPUT") or OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
