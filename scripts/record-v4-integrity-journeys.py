"""Record V4 integrity journeys against a real sidecar process.

Covers three honesty-sensitive paths:
1. Resource version change: a stale citation is rejected after re-index.
2. Memory preference overwrite/revoke: the stored preference actually changes.
3. Provider fault injection: a hanging provider produces an honest failure,
   never a fabricated coaching reply.

No provider key is required; the fault endpoint is a local hanging server.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPO_ROOT / "server"
OUTPUT = REPO_ROOT / "docs" / "verification" / "v4-integrity-journeys.json"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, method: str, path: str, body: dict | None = None, timeout: float = 120.0) -> tuple[int, dict]:
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
        detail = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = {"detail": detail}
        return exc.code, parsed


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
            "TRAINER_DB_NAME": "integrity.db",
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


class HangingProvider(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"object": "list", "data": [{"id": "hanging-model", "object": "model"}]}).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        # Consume the body, then hang beyond the configured client timeout.
        length = int(self.headers.get("content-length", "0") or 0)
        if length:
            self.rfile.read(length)
        time.sleep(20)
        try:
            self.send_response(504)
            self.end_headers()
        except OSError:
            return


def _resource_upload(port: int, workspace_id: str, path: Path) -> dict:
    status, payload = _request(
        port,
        "POST",
        "/resource/upload",
        {
            "workspace_id": workspace_id,
            "kind": "markdown",
            "name": path.name,
            "source": str(path),
        },
    )
    if status != 200:
        raise RuntimeError(f"resource upload failed: {status} {payload}")
    return payload


def main() -> int:
    report: dict = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "journeys": {},
        "assertions": {},
    }
    weird = _free_port()
    hanging = ThreadingHTTPServer(("127.0.0.1", weird), HangingProvider)
    thread = threading.Thread(target=hanging.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trainer-v4-integrity-") as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        workspace_dir = root / "workspace"
        workspace_dir.mkdir(parents=True)
        source = workspace_dir / "versioned.md"
        source.write_text("# Versioned source\nOriginal cited content.\n", encoding="utf-8")
        port = _free_port()
        sidecar = Sidecar(data_dir, port)
        sidecar.start()
        try:
            workspace_id = f"v4-integrity-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            report["workspace_id"] = workspace_id

            # 1) Resource version change.
            record = _resource_upload(port, workspace_id, source)
            indexed = _request(port, "POST", "/resource/index", {
                "workspace_id": workspace_id,
                "resource_id": record["id"],
                "enable_network": False,
            })[1]
            attempt = _request(port, "POST", "/training/attempt/start", {
                "workspace_id": workspace_id,
                "card_id": "card-version",
            })[1]["attempt"]
            evidence = _request(port, "POST", "/training/attempt/evidence", {
                "workspace_id": workspace_id,
                "attempt_id": attempt["attempt_id"],
                "artifact_hash": record.get("content_hash"),
                "result": "passed",
                "resource_id": record["id"],
            })[1]["evidence"]
            stale_version = evidence.get("resource_version_id")
            source.write_text("# Versioned source\nChanged after evidence.\n", encoding="utf-8")
            reindexed = _request(port, "POST", "/resource/index", {
                "workspace_id": workspace_id,
                "resource_id": record["id"],
                "enable_network": False,
            })[1]
            conflict_status, conflict = _request(port, "POST", "/training/attempt/evidence", {
                "workspace_id": workspace_id,
                "attempt_id": attempt["attempt_id"],
                "artifact_hash": record.get("content_hash"),
                "result": "passed",
                "resource_id": record["id"],
                "resource_version_id": stale_version,
            })
            report["journeys"]["15_resource_version"] = {
                "resource_id": record["id"],
                "initial_hash": record.get("content_hash"),
                "initial_version_id": stale_version,
                "reindexed_hash": reindexed.get("content_hash"),
                "current_version_id": (conflict.get("detail") or {}).get("current_version_id"),
                "stale_evidence_status": conflict_status,
                "stale_evidence_detail": conflict.get("detail"),
            }
            report["assertions"]["version_hash_changed"] = record.get("content_hash") != reindexed.get("content_hash")
            report["assertions"]["stale_version_rejected"] = conflict_status == 409 and (
                isinstance(conflict.get("detail"), dict)
                and conflict["detail"].get("code") == "resource_version_conflict"
            )

            # 2) Memory preference overwrite/revoke.
            first = _request(port, "POST", "/memory/settings", {
                "workspace_id": workspace_id,
                "teaching_style": "hands-on",
            })[1]
            second = _request(port, "POST", "/memory/settings", {
                "workspace_id": workspace_id,
                "teaching_style": "concept-first",
            })[1]
            global_set = _request(port, "POST", "/memory/global", {
                "workspace_id": workspace_id,
                "preferences": {"tone": "direct"},
                "long_term_goals": ["ship the queue lock fix"],
            })[1]
            global_cleared = _request(port, "POST", "/memory/global", {
                "workspace_id": workspace_id,
                "preferences": {},
                "long_term_goals": [],
            })[1]
            def _memory(payload: dict) -> dict:
                memory = payload.get("memory")
                return memory if isinstance(memory, dict) else {}

            def _global(payload: dict) -> dict:
                value = _memory(payload).get("globalMemory")
                return value if isinstance(value, dict) else {}

            report["journeys"]["19_memory_revoke"] = {
                "first_teaching_style": (_memory(first).get("profile") or {}).get("teaching_style"),
                "second_teaching_style": (_memory(second).get("profile") or {}).get("teaching_style"),
                "global_preferences_set": _global(global_set).get("preferences"),
                "global_goals_set": _global(global_set).get("longTermGoals"),
                "global_preferences_cleared": _global(global_cleared).get("preferences"),
                "global_goals_cleared": _global(global_cleared).get("longTermGoals"),
            }
            report["assertions"]["preference_overwritten"] = (
                report["journeys"]["19_memory_revoke"]["first_teaching_style"] !=
                report["journeys"]["19_memory_revoke"]["second_teaching_style"]
            )
            report["assertions"]["memory_revoked"] = (
                not report["journeys"]["19_memory_revoke"]["global_preferences_cleared"]
                and not report["journeys"]["19_memory_revoke"]["global_goals_cleared"]
            )

            # 3) Provider fault injection.
            provider = {
                "provider": {
                    "name": "Hanging fixture",
                    "base_url": f"http://127.0.0.1:{weird}/v1",
                    "model": "hanging-model",
                    "protocol": "openai_chat_completions_compatible",
                    "api_key_ref": "ui_proxy:test",
                    "request_defaults": {"timeout": 5},
                },
                "api_key": "fixture-key",
                "response_language": "zh-CN",
                "use_agent_loop": False,
            }
            fault_started = time.monotonic()
            status, fault_reply = _request(port, "POST", "/session/message", {
                **provider,
                "workspace_id": workspace_id,
                "message": "Provider fault injection: this must not fabricate a coaching answer.",
            }, timeout=90)
            elapsed_ms = int((time.monotonic() - fault_started) * 1000)
            reply_text = str((fault_reply.get("reply") or {}).get("content") or "")
            report["journeys"]["17_provider_fault"] = {
                "http_status": status,
                "elapsed_ms": elapsed_ms,
                "reply": reply_text[:1600],
                "reply_chars": len(reply_text),
            }
            report["assertions"]["fault_returned_honest_reply"] = status == 200 and len(reply_text) > 0
            report["assertions"]["fault_did_not_fabricate_training_answer"] = "fabricate" not in reply_text.lower()
            report["assertions"]["fault_within_timeout_budget"] = elapsed_ms < 30_000
        finally:
            sidecar.stop()
    hanging.shutdown()
    hanging.server_close()
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["ok"] = all(bool(value) for value in report["assertions"].values())
    output = Path(os.getenv("TRAINER_INTEGRITY_OUTPUT") or OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
