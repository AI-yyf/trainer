"""Real Sidecar Experience Matrix (in-process ASGI + SQLite + Sandbox + 4-Protocol Loop).

Exercises the live FastAPI sidecar (`create_app`) end-to-end across 12 canonical
architectural invariants without relying on loopback TCP sockets or external API keys:

1. Resident session LRU bounding (<= 64) + transparent SQLite eviction & rehydration.
2. Unbuffered live SSE `text_delta` delivery in default `auto` answer policy.
3. 4-wire-protocol streaming `usage` accounting (`OpenAI Chat`, `OpenAI Responses`,
   `Gemini GenerateContent`, `Anthropic Messages`) feeding `CoachAgentLoop`.
4. Asymmetric dual-space isolation (`<ProjectRoot>` read-only vs `<LibraryRoot>` R/W).
5. `library_exec` kernel/audit jail blocking obfuscated writes to `<ProjectRoot>`.
6. Resource lifecycle: upload -> index -> lexical search -> soft-delete -> restore.
7. Cross-workspace strict resource & memory isolation.
8. Cross-turn compact `[Prior turn tool trace: ...]` continuity in conversation history.
9. Context-tier discipline: idle open editor tab stays on `minimal` prompt tier.
10. Training attempt + snippet evaluator + unified SQLite `event_ledger` closure.
11. Browser capture pairing, draft submission, host visibility, and acknowledgement.
12. Byte-0 static coaching prompt prefix invariance across views and skill triggers.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.api.runtime import MAX_RESIDENT_SESSIONS  # noqa: E402
from app.core.models import ChatMessage, UserProfile, utc_now_iso  # noqa: E402
from app.llm.agent_binding import ProviderAgentBinding  # noqa: E402
from app.llm.prompts import build_coaching_messages, build_static_coaching_prefix  # noqa: E402
from app.llm.provider_service import ProviderService  # noqa: E402
from app.llm.tools import ToolContext, build_default_tool_registry  # noqa: E402
from app.main import create_app  # noqa: E402


class _AsyncIterList:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def __aiter__(self):
        async def _gen():
            for item in self._items:
                yield item

        return _gen()


async def _run_matrix() -> dict[str, Any]:
    started_at = time.monotonic()
    scenarios: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: dict[str, Any]) -> None:
        scenarios.append({"id": name, "status": "passed" if ok else "failed", "detail": detail})

    with tempfile.TemporaryDirectory(prefix="trainer-sidecar-matrix-") as tmp_root:
        root_dir = Path(tmp_root)
        data_dir = root_dir / ".trainer" / "runtime"
        project_dir = root_dir / "learner_project"
        project_dir.mkdir(parents=True, exist_ok=True)
        readme_file = project_dir / "README.md"
        readme_file.write_text("# Learner Project\nprint('hello')\n", encoding="utf-8")

        with patch.dict(os.environ, {"TRAINER_DATA_DIR": str(data_dir), "TRAINER_SIDECAR_TOKEN": ""}):
            app = create_app()
        runtime = app.state.runtime
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="https://sidecar.test") as client:
            # 1. Session LRU bounding + SQLite rehydration
            created_sessions: list[str] = []
            total_to_create = MAX_RESIDENT_SESSIONS + 6
            for idx in range(total_to_create):
                resp = await client.post(
                    "/session/start",
                    json={
                        "workspace_id": f"ws-lru-{idx}",
                        "workspace_name": f"Workspace {idx}",
                    },
                )
                assert resp.status_code == 200, resp.text
                created_sessions.append(resp.json()["session_id"])

            resident_after_burst = len(runtime.sessions)
            evicted_first = created_sessions[0] not in dict.keys(runtime.sessions)
            rehydrated = await client.post(
                "/session/start",
                json={
                    "session_id": created_sessions[0],
                    "workspace_id": "ws-lru-0",
                    "workspace_name": "Workspace 0",
                },
            )
            record(
                "01_session_lru_bound_and_rehydration",
                resident_after_burst <= MAX_RESIDENT_SESSIONS
                and evicted_first
                and rehydrated.status_code == 200
                and rehydrated.json().get("session_id") == created_sessions[0],
                {
                    "created": total_to_create,
                    "resident_cap": MAX_RESIDENT_SESSIONS,
                    "resident_count": resident_after_burst,
                    "evicted_cold_oldest": evicted_first,
                },
            )

            # 2. Live unbuffered SSE streaming in default `auto` policy
            start_main = await client.post(
                "/session/start",
                json={
                    "workspace_id": "ws-matrix-main",
                    "workspace_name": "Matrix Main",
                    "workspace_path": str(project_dir),
                    "profile": {
                        "long_term_goal": "Master distributed systems",
                        "weekly_hours": 5,
                        "teaching_style": "guided",
                        "answer_policy": "auto",
                    },
                },
            )
            session_main = start_main.json()["session_id"]

            stub_provider = {
                "name": "matrix-stub",
                "baseUrl": "https://api.openai.com/v1",
                "apiKeyRef": "matrix-stub-ref",
                "model": "gpt-4o-mini",
                "protocol": "openai_chat_completions",
            }
            verified_test_stamp = {
                "ok": True,
                "baseUrl": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "protocol": "openai_chat_completions",
                "checkedAt": utc_now_iso(),
                "capabilityEvidence": [
                    {"name": "streaming", "state": "verified", "observed": True},
                    {"name": "tools", "state": "verified", "observed": True},
                ],
            }

            async def _fake_live_chunks(*_args: Any, **_kwargs: Any):
                for piece in ("我们先看项目里的 ", "`README.md` 最小入口，", "定位第一处调用位置，", "再一步步验证返回值与断言结果。"):
                    yield piece

            with patch.object(
                ProviderService,
                "_plain_completion_uses_agent_binding",
                return_value=True,
            ), patch.object(
                ProviderService,
                "_completion_stream_via_agent_binding",
                side_effect=_fake_live_chunks,
            ):
                sse_resp = await client.post(
                    "/turn/stream",
                    headers={"accept": "text/event-stream"},
                    json={
                        "session_id": session_main,
                        "workspace_id": "ws-matrix-main",
                        "intent": "coach",
                        "message": "帮我看看入口该怎么理解",
                        "response_language": "zh-CN",
                        "answer_mode": "auto",
                        "use_agent_loop": False,
                        "provider": stub_provider,
                        "api_key": "sk-matrix-stub",
                        "last_test_result": verified_test_stamp,
                    },
                )
                sse_body = sse_resp.text
                chunk_events = [
                    line for line in sse_body.splitlines() if '"chunk"' in line and line.startswith("data:")
                ]
                has_complete = "event: complete" in sse_body
            record(
                "02_live_unbuffered_sse_streaming_default_auto",
                sse_resp.status_code == 200 and len(chunk_events) >= 2 and has_complete,
                {"status": sse_resp.status_code, "chunk_frames": len(chunk_events), "has_complete": has_complete},
            )

            # 3. 4-wire-protocol streaming usage accounting
            protocol_usages: dict[str, dict[str, Any] | None] = {}

            # 3a. OpenAI Chat Completions stream with trailing choices=[] usage chunk
            chat_svc = MagicMock()
            chat_svc._config = SimpleNamespace(
                base_url="https://api.openai.com/v1",
                model="gpt-4o-mini",
                protocol="openai_chat_completions",
                capabilities=SimpleNamespace(vision=False),
                request_defaults={},
            )
            chat_svc._api_key = "sk-test"
            chat_svc._resolve_model.return_value = "gpt-4o-mini"
            chat_svc._model_candidates.return_value = ["gpt-4o-mini"]
            chat_svc._apply_request_defaults.side_effect = lambda d: d
            chat_stream_chunks = _AsyncIterList([
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello world.", tool_calls=None), finish_reason=None)],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None), finish_reason="stop")],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=120,
                        completion_tokens=18,
                        total_tokens=138,
                        prompt_tokens_details=SimpleNamespace(cached_tokens=64),
                        completion_tokens_details=SimpleNamespace(reasoning_tokens=4),
                    ),
                ),
            ])
            chat_svc._create_chat_completion_negotiated_async = AsyncMock(return_value=chat_stream_chunks)
            chat_binding = ProviderAgentBinding(provider_service=chat_svc, protocol="openai_chat_completions")
            # build_agent_provider() always wires call_stream; narrow the Optional field for the type checker.
            chat_call_stream = chat_binding.build_agent_provider().call_stream
            assert chat_call_stream is not None
            chat_events = [ev async for ev in chat_call_stream([{"role": "user", "content": "hi"}], None)]
            protocol_usages["openai_chat_completions"] = chat_events[-1].get("usage")

            # 3b. OpenAI Responses stream
            resp_svc = MagicMock()
            resp_svc._config = SimpleNamespace(
                base_url="https://api.openai.com/v1",
                model="gpt-4.1-mini",
                protocol="openai_responses",
                capabilities=SimpleNamespace(vision=False),
                request_defaults={},
            )
            resp_svc._api_key = "sk-test"
            resp_svc._resolve_model.return_value = "gpt-4.1-mini"
            resp_svc._model_candidates.return_value = ["gpt-4.1-mini"]

            class _FakeResponsesStream:
                def __aiter__(self):
                    async def _gen():
                        yield SimpleNamespace(type="response.output_text.delta", delta="Responses ok.")
                        yield SimpleNamespace(type="response.completed")

                    return _gen()

                async def get_final_response(self):
                    return SimpleNamespace(
                        status="completed",
                        output_text="Responses ok.",
                        output=[],
                        usage=SimpleNamespace(
                            input_tokens=200,
                            output_tokens=22,
                            total_tokens=222,
                            input_tokens_details=SimpleNamespace(cached_tokens=100),
                            output_tokens_details=SimpleNamespace(reasoning_tokens=6),
                        ),
                    )

            class _FakeResponsesCM:
                async def __aenter__(self):
                    return _FakeResponsesStream()

                async def __aexit__(self, *_args: Any):
                    return False

            resp_client = MagicMock()
            resp_client.responses.stream.return_value = _FakeResponsesCM()
            resp_svc._get_client.return_value = resp_client
            resp_binding = ProviderAgentBinding(provider_service=resp_svc, protocol="openai_responses")
            resp_call_stream = resp_binding.build_agent_provider().call_stream
            assert resp_call_stream is not None
            resp_events = [ev async for ev in resp_call_stream([{"role": "user", "content": "hi"}], None)]
            protocol_usages["openai_responses"] = resp_events[-1].get("usage")

            # 3c. Gemini GenerateContent stream
            gem_svc = MagicMock()
            gem_svc._config = SimpleNamespace(
                base_url="https://generativelanguage.googleapis.com/v1beta",
                model="gemini-2.5-flash",
                protocol="gemini_generate_content",
                capabilities=SimpleNamespace(vision=False),
                request_defaults={},
            )
            gem_svc._api_key = "gem-key"
            gem_binding = ProviderAgentBinding(provider_service=gem_svc, protocol="gemini_generate_content")

            class _FakeSSEStreamResponse:
                def __init__(self, lines: list[str]) -> None:
                    self.status_code = 200
                    self._lines = lines

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args: Any):
                    return False

                async def aiter_lines(self):
                    for line in self._lines:
                        yield line

            class _FakeHTTPClient:
                def __init__(self, lines: list[str]) -> None:
                    self._lines = lines

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args: Any):
                    return False

                def stream(self, *_args: Any, **_kwargs: Any):
                    return _FakeSSEStreamResponse(self._lines)

            gem_lines = [
                "data: " + json.dumps({
                    "candidates": [{"content": {"parts": [{"text": "Gemini ok."}]}, "finishReason": "STOP"}],
                    "usageMetadata": {
                        "promptTokenCount": 150,
                        "candidatesTokenCount": 15,
                        "thoughtsTokenCount": 5,
                        "cachedContentTokenCount": 50,
                        "totalTokenCount": 170,
                    },
                }),
            ]
            with patch.object(gem_binding, "_async_http_client", return_value=_FakeHTTPClient(gem_lines)):
                gem_call_stream = gem_binding.build_agent_provider().call_stream
                assert gem_call_stream is not None
                gem_events = [ev async for ev in gem_call_stream([{"role": "user", "content": "hi"}], None)]
            protocol_usages["gemini_generate_content"] = gem_events[-1].get("usage")

            # 3d. Anthropic Messages stream
            anth_svc = MagicMock()
            anth_svc._config = SimpleNamespace(
                base_url="https://api.anthropic.com",
                model="claude-sonnet-4-20250514",
                protocol="anthropic_messages",
                capabilities=SimpleNamespace(vision=False),
                request_defaults={},
            )
            anth_svc._api_key = "sk-ant-test"
            anth_binding = ProviderAgentBinding(provider_service=anth_svc, protocol="anthropic_messages")
            anth_lines = [
                "data: " + json.dumps({
                    "type": "message_start",
                    "message": {
                        "usage": {
                            "input_tokens": 90,
                            "cache_read_input_tokens": 40,
                            "cache_creation_input_tokens": 10,
                            "output_tokens": 1,
                        }
                    },
                }),
                "data: " + json.dumps({
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Anthropic ok."},
                }),
                "data: " + json.dumps({
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 24},
                }),
                "data: " + json.dumps({"type": "message_stop"}),
            ]
            with patch.object(anth_binding, "_async_http_client", return_value=_FakeHTTPClient(anth_lines)):
                anth_call_stream = anth_binding.build_agent_provider().call_stream
                assert anth_call_stream is not None
                anth_events = [ev async for ev in anth_call_stream([{"role": "user", "content": "hi"}], None)]
            protocol_usages["anthropic_messages"] = anth_events[-1].get("usage")

            all_4_ok = all(
                isinstance(u, dict) and int(u.get("input_tokens") or 0) > 0 and int(u.get("output_tokens") or 0) > 0
                for u in protocol_usages.values()
            )
            record("03_four_protocol_streaming_usage_accounting", all_4_ok, protocol_usages)

            # 4 & 5. Asymmetric dual-space isolation + library_exec jail
            registry = build_default_tool_registry()
            tool_ctx = ToolContext(
                runtime=runtime,
                workspace_id="ws-matrix-main",
                session_id=session_main,
                response_language="zh-CN",
                extra={"active_view": "resources", "library_sandbox_work": True},
            )
            proj_read = await registry.invoke(tool_ctx, "project_read", {"action": "read", "path": "README.md"})
            proj_write_denied = await registry.invoke(tool_ctx, "write_file", {"path": "README.md", "content": "pwn"})
            lib_write = await registry.invoke(
                tool_ctx,
                "library_write",
                {"action": "write", "path": "notes/summary.md", "content": "# Matrix Note\nVerified.\n"},
            )
            lib_read = await registry.invoke(
                tool_ctx,
                "library_read",
                {"action": "read_file", "path": "notes/summary.md"},
            )
            record(
                "04_dual_space_project_readonly_vs_library_rw",
                proj_read.get("ok") is True
                and proj_write_denied.get("ok") is False
                and lib_write.get("ok") is True
                and lib_read.get("ok") is True
                and "Matrix Note" in str(lib_read.get("content") or ""),
                {
                    "project_read_ok": proj_read.get("ok"),
                    "project_write_blocked": proj_write_denied.get("error"),
                    "library_write_ok": lib_write.get("ok"),
                },
            )

            exec_ok = await registry.invoke(
                tool_ctx,
                "library_exec",
                {"command": "python3 -c \"from pathlib import Path; print(Path('notes/summary.md').read_text().splitlines()[0])\""},
            )
            exploit_cmd = (
                f"python3 -c \"import pathlib; pathlib.Path({str(readme_file)!r}).write_text('HACKED')\""
            )
            exec_blocked = await registry.invoke(tool_ctx, "library_exec", {"command": exploit_cmd})
            readme_intact = readme_file.read_text(encoding="utf-8").startswith("# Learner Project")
            record(
                "05_library_exec_jail_blocks_project_write",
                exec_ok.get("ok") is True
                and "# Matrix Note" in str(exec_ok.get("stdout") or "")
                and exec_blocked.get("ok") is False
                and readme_intact,
                {
                    "sandbox_exec_ok": exec_ok.get("ok"),
                    "exploit_blocked": exec_blocked.get("ok") is False,
                    "project_readme_intact": readme_intact,
                },
            )

            # 6 & 7. Resource upload -> index -> search -> trash -> restore + cross-workspace isolation
            upload = await client.post(
                "/resource/upload",
                json={
                    "session_id": session_main,
                    "workspace_id": "ws-matrix-main",
                    "name": "raft_consensus.md",
                    "kind": "markdown",
                    "source": "file",
                    "content": "# Raft Consensus\nLeader election uses randomized election timeouts and term numbers.\n",
                },
            )
            res_id = upload.json().get("id") or upload.json().get("resource_id")
            idx_resp = await client.post(
                "/resource/index",
                json={"workspace_id": "ws-matrix-main", "resource_id": res_id, "enable_network": False},
            )
            search_a = await client.post(
                "/resource/search",
                json={"session_id": session_main, "workspace_id": "ws-matrix-main", "query": "randomized election"},
            )
            hits_a = [h.get("id") or h.get("resource_id") for h in (search_a.json().get("hits") or [])]

            # Workspace B isolation check
            start_b = await client.post(
                "/session/start",
                json={"workspace_id": "ws-matrix-isolated", "workspace_name": "Isolated B"},
            )
            search_b = await client.post(
                "/resource/search",
                json={
                    "session_id": start_b.json()["session_id"],
                    "workspace_id": "ws-matrix-isolated",
                    "query": "randomized election",
                },
            )
            hits_b = [h.get("id") or h.get("resource_id") for h in (search_b.json().get("hits") or [])]

            del_res = await registry.invoke(
                tool_ctx,
                "library_write",
                {"action": "soft_delete", "resource_id": res_id},
            )
            restore_res = await registry.invoke(
                tool_ctx,
                "library_write",
                {"action": "restore", "resource_id": res_id},
            )
            record(
                "06_resource_upload_index_search_trash_restore",
                upload.status_code == 200
                and idx_resp.status_code == 200
                and res_id in hits_a
                and del_res.get("ok") is True
                and restore_res.get("ok") is True,
                {"resource_id": res_id, "found_in_search": res_id in hits_a},
            )
            record(
                "07_cross_workspace_strict_isolation",
                search_b.status_code == 200 and res_id not in hits_b,
                {"workspace_b_hits": hits_b},
            )

            # 8. Cross-turn tool trace continuity
            state_main = runtime.ensure_session(session_main, workspace_id="ws-matrix-main")
            state_main.snapshot.messages.extend([
                ChatMessage(id="m-u1", role="user", content="帮我看看项目里的 README.md 入口", metadata={"active_view": "coach"}),
                ChatMessage(
                    id="m-a1",
                    role="assistant",
                    content="我已经读取了项目里的 README.md 最小入口文件。",
                    metadata={
                        "active_view": "coach",
                        "parts": [
                            {
                                "type": "tool_result",
                                "callId": "call-1",
                                "name": "project_read",
                                "result": {"ok": True, "action": "read", "path": "README.md"},
                            }
                        ],
                    },
                ),
            ])
            runtime.save_session_state(session_main)
            # Verify via prompt builder + router history helper through snapshot round-trip
            snap_resp = await client.get("/snapshot", params={"session_id": session_main, "workspace_id": "ws-matrix-main"})
            snap_messages = (snap_resp.json().get("snapshot") or {}).get("messages") or []
            persisted_parts = (
                snap_messages[-1].get("metadata", {}).get("parts", [])
                if snap_messages
                else []
            )
            # Trigger one scripted turn to verify build_conversation_history injects `[Prior turn tool trace: ...]`
            captured_messages: list[dict[str, Any]] = []

            async def _capture_turn_messages(msgs: list[dict[str, Any]], **_kw: Any):
                captured_messages.extend(msgs)
                yield "刚才读取了 `README.md`。"

            with patch.object(
                ProviderService,
                "_plain_completion_uses_agent_binding",
                return_value=True,
            ), patch.object(
                ProviderService,
                "_completion_stream_via_agent_binding",
                side_effect=_capture_turn_messages,
            ):
                await client.post(
                    "/turn/stream",
                    headers={"accept": "text/event-stream"},
                    json={
                        "session_id": session_main,
                        "workspace_id": "ws-matrix-main",
                        "intent": "coach",
                        "active_view": "coach",
                        "message": "确认一下刚才读了哪个文件？",
                        "response_language": "zh-CN",
                        "answer_mode": "direct",
                        "use_agent_loop": False,
                        "provider": stub_provider,
                        "api_key": "sk-matrix-stub",
                        "last_test_result": verified_test_stamp,
                    },
                )
            trace_preserved = any(
                "[Prior turn tool trace: project_read(read):README.md[ok]]" in str(m.get("content") or "")
                for m in captured_messages
            )
            record(
                "08_cross_turn_tool_trace_continuity",
                bool(persisted_parts) and trace_preserved,
                {"trace_injected_into_history": trace_preserved},
            )

            # 9. Idle editor tab stays on minimal prompt tier
            captured_idle_tier_messages: list[dict[str, Any]] = []

            async def _capture_idle_tier(msgs: list[dict[str, Any]], **_kw: Any):
                captured_idle_tier_messages.extend(msgs)
                yield "我们可以先定学习目标。"

            with patch.object(
                ProviderService,
                "_plain_completion_uses_agent_binding",
                return_value=True,
            ), patch.object(
                ProviderService,
                "_completion_stream_via_agent_binding",
                side_effect=_capture_idle_tier,
            ):
                await client.post(
                    "/turn/stream",
                    headers={"accept": "text/event-stream"},
                    json={
                        "session_id": session_main,
                        "workspace_id": "ws-matrix-main",
                        "intent": "coach",
                        "active_view": "coach",
                        "message": "我想制定两周并发学习目标",
                        "response_language": "zh-CN",
                        "answer_mode": "direct",
                        "use_agent_loop": False,
                        "provider": stub_provider,
                        "api_key": "sk-matrix-stub",
                        "last_test_result": verified_test_stamp,
                        "current_file": {
                            "path": "README.md",
                            "language_id": "markdown",
                            "content": "# Idle open tab\n",
                        },
                    },
                )
            sys_len = len(str(captured_idle_tier_messages[0].get("content") or "")) if captured_idle_tier_messages else 99999
            record(
                "09_idle_editor_tab_minimal_prompt_tier",
                0 < sys_len < 4500,
                {"system_prompt_chars": sys_len},
            )

            # 10. Training attempt + evaluator + SQLite event_ledger closure
            attempt_start = await client.post(
                "/training/attempt/start",
                json={"workspace_id": "ws-matrix-main", "card_id": "matrix-card-1", "assistance_level": "independent"},
            )
            attempt_id = (attempt_start.json().get("attempt") or {}).get("attempt_id")
            await client.post(
                "/training/attempt/update",
                json={"attempt_id": attempt_id, "workspace_id": "ws-matrix-main", "answer_draft": "x = 1", "status": "submitted"},
            )
            ev_resp = await client.post(
                "/training/attempt/evidence",
                json={
                    "attempt_id": attempt_id,
                    "workspace_id": "ws-matrix-main",
                    "artifact_hash": "sha256:matrix-1",
                    "result": "pass",
                    "runner_version": "matrix-1.0",
                    "execution_location": "workspace",
                },
            )
            eval_resp = await client.post(
                "/evaluate/snippet",
                json={
                    "session_id": session_main,
                    "workspace_id": "ws-matrix-main",
                    "language_id": "python",
                    "content": "def add(a, b):\n    return a + b\nassert add(2, 3) == 5\n",
                },
            )
            record(
                "10_training_attempt_and_snippet_evaluator",
                attempt_start.status_code == 200
                and bool(attempt_id)
                and ev_resp.status_code == 200
                and eval_resp.status_code == 200,
                {"attempt_id": attempt_id, "evidence_status": ev_resp.status_code, "eval_status": eval_resp.status_code},
            )

            # 11. Browser bridge 6-digit pairing + pending draft lifecycle
            ext_origin = "chrome-extension://" + ("a" * 32)
            pair_code = "482916"
            pair_code_resp = await client.post(
                "/browser/pair-code",
                json={"code": pair_code, "workspace_id": "ws-matrix-main"},
            )
            pair = await client.post(
                "/browser/pair",
                json={"code": pair_code},
                headers={"Origin": ext_origin},
            )
            cred = pair.json().get("credential") or pair.json().get("token") or ""
            paired_ws = pair.json().get("workspace_id") or "ws-matrix-main"
            draft = await client.post(
                "/browser/coach-draft",
                json={
                    "selection": "Raft uses randomized election timeouts.",
                    "url": "https://raft.github.io/",
                    "title": "Raft Paper",
                    "client_id": "matrix-draft-1",
                },
                headers={"Authorization": f"Bearer {cred}", "Origin": ext_origin},
            )
            draft_id = draft.json().get("draft_id") or draft.json().get("id") or ""
            pending = await client.get("/browser/pending-drafts", params={"workspace_id": paired_ws})
            pending_ids = [d.get("id") or d.get("draft_id") for d in (pending.json().get("drafts") or [])]
            ack = await client.post(
                "/browser/pending-drafts/ack",
                json={"workspace_id": paired_ws, "ids": [draft_id]},
            )
            record(
                "11_browser_bridge_pair_draft_and_ack",
                pair_code_resp.status_code == 200
                and pair.status_code == 200
                and bool(cred)
                and draft_id in pending_ids
                and ack.status_code == 200,
                {"draft_id": draft_id, "acked": ack.status_code == 200},
            )

            # 12. Static byte-0 coaching prompt prefix invariance
            profile = UserProfile(long_term_goal="Master distributed systems", teaching_style="guided")
            static_prefix = build_static_coaching_prefix(profile)
            msgs_a = build_coaching_messages(
                profile=profile,
                message="Explain Raft log replication",
                response_language="zh-CN",
                coach_context={"active_view": "coach", "context_tier": "full"},
            )
            msgs_b = build_coaching_messages(
                profile=profile,
                message=" Organize my Raft notes ",
                response_language="en-US",
                coach_context={"active_view": "resources", "context_tier": "full"},
            )
            sys_a = str(msgs_a[0]["content"])
            sys_b = str(msgs_b[0]["content"])
            prefix_locked = (
                len(static_prefix) > 10_000
                and sys_a.startswith(static_prefix)
                and sys_b.startswith(static_prefix)
            )
            record(
                "12_static_kv_cache_prefix_invariance",
                prefix_locked,
                {"static_prefix_chars": len(static_prefix)},
            )

    passed = [s for s in scenarios if s["status"] == "passed"]
    failed = [s for s in scenarios if s["status"] != "passed"]
    return {
        "suite": "real_sidecar_experience_matrix",
        "elapsed_ms": round((time.monotonic() - started_at) * 1000, 1),
        "total": len(scenarios),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "scenarios": scenarios,
    }


def main() -> int:
    report = asyncio.run(_run_matrix())
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
