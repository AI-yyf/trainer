import copy
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import EvaluationReport, ProviderConfig, ReviewArtifactSnapshot
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.llm.stream_agent_metadata import merge_stream_agent_metadata
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


def test_live_save_evidence_survives_auto_resource_preparation_metadata():
    automatic = {"type": "tool_result", "id": "auto-search-resources",
                 "name": "search_resources", "auto": True}
    save = {"type": "tool_result", "id": "save-one", "name": "save_formal_plan",
            "result": {"ok": True, "committed": True}}
    prepared = {"agentic": False, "stop_reason": "completed", "tool_events": [automatic]}
    live = {"agentic": True, "stop_reason": "coach_finalize", "tool_events": [save],
            "steps": [{"index": 1}]}
    before = copy.deepcopy(prepared)
    merged = merge_stream_agent_metadata(prepared, live)
    assert merged["tool_events"] == [automatic, save]
    assert merged["steps"] == [{"index": 1}]
    assert merged["agentic"] is True
    assert merged["stop_reason"] == "coach_finalize"
    assert prepared == before
    assert merge_stream_agent_metadata(merged, live)["tool_events"] == [automatic, save]


def test_terminal_failure_is_preserved_without_erasing_committed_tool_evidence():
    failure = {"stop_reason": "timeout", "summary": "Provider timed out.",
               "tool_events": []}
    live = {"stop_reason": "completed", "summary": None, "tool_events": [
        {"type": "tool_result", "id": "saved", "name": "save_formal_plan",
         "result": {"ok": True, "committed": True}}]}
    merged = merge_stream_agent_metadata(failure, live, preserve_failure=True)
    assert merged["stop_reason"] == "timeout"
    assert merged["summary"] == "Provider timed out."
    assert merged["tool_events"] == live["tool_events"]


def client_with_provider(tmp_path):
    app = create_app(AppSettings(
        app_name="Trainer stream evidence test", host="127.0.0.1", port=8765,
        data_dir=tmp_path, database_name="stream-evidence.sqlite3",
        default_session_stage="intake", summary_message_limit=6, enable_network_fetch=False,
    ))
    provider = ProviderConfig(name="fixture", base_url="http://127.0.0.1:9/v1",
                              api_key_ref="fixture", model="fixture",
                              capabilities={"chat": True, "tools": True, "streaming": True})
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "test-fixture-key"
    runtime.provider_service = ProviderService(config=provider, api_key="test-fixture-key")
    seed_verified_capabilities(runtime, provider, "test-fixture-key")
    return TestClient(app)


def test_streamed_formal_save_with_automatic_resources_reports_actual_commit(tmp_path):
    captured = {}

    async def save_stream(self, profile, message, current_file=None, **kwargs):
        context = kwargs["coach_context"]
        captured["auto"] = context.get("auto_resource_lookup")
        arguments = {"title": "Python recall plan", "summary": "One concrete boundary",
                     "stages": [{"title": "Tuple slots", "goal": "Explain mutation"}]}
        yield {"type": "tool_call", "id": "save-one", "name": "save_formal_plan",
               "arguments": arguments}
        result = await build_default_tool_registry().invoke(ToolContext(
            runtime=context["__runtime__"], workspace_id=context["workspace_id"],
            session_id=context["session_id"], profile=profile,
            extra={"formal_plan_mutation": True, "allow_coach_only_tools": True}),
            "save_formal_plan", arguments)
        assert result["ok"] is True and result["committed"] is True
        yield {"type": "tool_result", "id": "save-one", "name": "save_formal_plan",
               "ok": True, "result": result}
        yield {"type": "final", "content": "Saved the formal plan.",
               "summary": "Saved the formal plan.", "next_step": "Explain tuple slots.",
               "stop_reason": "coach_finalize"}

    with client_with_provider(tmp_path) as client:
        start = client.post("/session/start", json={"workspace_id": "stream-save", "workspace_name": "stream-save",
            "profile": {"long_term_goal": "Learn Python", "weekly_hours": 2}})
        assert start.status_code == 200, start.text
        session_id = start.json()["session_id"]
        upload = client.post("/resource/upload", json={"workspace_id": "stream-save",
            "session_id": session_id, "kind": "markdown", "name": "Python.md",
            "source": "inline://Python.md", "content": "Python tuple slots and list mutation",
            "content_encoding": "utf-8"})
        assert upload.status_code == 200, upload.text
        indexed = client.post("/resource/index", json={"workspace_id": "stream-save",
            "session_id": session_id, "resource_id": upload.json()["id"]})
        assert indexed.status_code == 200, indexed.text
        with patch.object(ProviderService, "coaching_reply_agentic_stream", save_stream):
            response = client.post("/turn/stream", json={"workspace_id": "stream-save",
                "session_id": session_id, "intent": "plan", "formalPlanMutation": True,
                "use_agent_loop": True, "message": "Explain Python tuple slots, then generate and save a formal plan."})
        assert response.status_code == 200, response.text
        frames = [json.loads(block.split("data: ", 1)[1]) for block in response.text.split("\n\n")
                  if block.startswith("event: complete\n")]
        assert frames
        body = frames[-1]
        assert captured["auto"] is True
        assert "not committed" not in json.dumps(body)
        assert "formal_plan_commit_missing" not in json.dumps(body)
        assert "save_formal_plan" in json.dumps(body)
        assert client.app.state.runtime.repository.get_latest_plan("stream-save") is not None


def test_recall_response_artifacts_do_not_reuse_a_saved_file_evaluation(tmp_path):
    captured = {}

    async def recall_reply(self, profile, message, current_file=None, **kwargs):
        captured.update(kwargs["coach_context"])
        return "元组槽位与引用对象的区别解释正确。"

    with client_with_provider(tmp_path) as client:
        start = client.post("/session/start", json={"workspace_id": "recall-artifact",
            "workspace_name": "recall-artifact", "profile": {"long_term_goal": "Learn Python"}})
        assert start.status_code == 200, start.text
        session_id = start.json()["session_id"]
        runtime = client.app.state.runtime
        structured = runtime.memory_service.structured_for_workspace("recall-artifact")
        structured._review_artifact = ReviewArtifactSnapshot(id="own-recall", title="复习：元组",
            focus_area="元组槽位", summary="解释槽位与引用对象的区别。", guardrail="先回忆，再核对例子。",
            status="resolved", verified_result="槽位不可赋值，引用的列表可以修改。")
        structured.update_workspace(latest_training_submode="review")
        runtime.repository.save_structured_memory("recall-artifact", structured.export_state())
        state = runtime.ensure_session(session_id, workspace_id="recall-artifact")
        state.snapshot.evaluation = EvaluationReport(summary="OLD pytest file check",
            next_step="RUN OLD coding verification", passed=True)
        runtime.save_session_state(session_id)
        with patch.object(ProviderService, "coaching_reply", recall_reply):
            response = client.post("/session/message", json={"workspace_id": "recall-artifact",
                "session_id": session_id, "active_view": "training", "use_agent_loop": False,
                "message": "请评价当前概念复习", "response_language": "zh-CN"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert captured["review_artifact"]["id"] == "own-recall"
        artifacts = body["artifacts"]
        assert set(artifacts) == {"review"}
        assert artifacts["review"]["metadata"]["evidence_scope"] == "self_reported_recall"
        assert artifacts["review"]["recommended_action"] is None
        assert "OLD" not in json.dumps(artifacts)
        assert all(action["action"] not in {"review", "retry_review", "task", "next_task"}
                   for action in body["suggested_actions"])
