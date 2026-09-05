import tempfile
from pathlib import Path

from app.core.models import ProviderConfig
from tests.test_api import build_client

BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL = "mimo-v2.5"
API_KEY = "tp-cc15zuo8wzdqxb4ib63gl1ukmho9fd8hi39g5jc3sknsmlns"


def main() -> None:
    workspace = Path(tempfile.mkdtemp(prefix="trainer-real-smoke-"))
    print("WORKDIR", workspace)
    provider_payload = {
        "name": "mimo-live",
        "base_url": BASE_URL,
        "api_key_ref": "trainer.mimo.live",
        "model": MODEL,
        "context_window_tokens": 65536,
        "max_output_tokens": 4096,
    }

    client = build_client(workspace, configure_provider=False)
    try:
        runtime = client.app.state.runtime
        runtime.provider_config = ProviderConfig.model_validate(provider_payload)
        runtime.provider_api_key = API_KEY
        runtime.provider_service_cache.clear()

        smoke = client.post("/provider/test", json={"provider": provider_payload, "api_key": API_KEY})
        smoke_payload = smoke.json()
        print("PROVIDER_TEST", smoke.status_code, smoke_payload.get("ok"), smoke_payload.get("detail"))

        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-real-stage2",
                "workspace_name": "trainer-real-stage2",
                "profile": {
                    "long_term_goal": "Use Trainer as a long-term code coach, not a coding agent",
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        start_payload = start.json()
        session_id = start_payload["session_id"]
        print("SESSION_START", start.status_code, session_id)

        settings = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "coach_defaults": {
                    "memory_scope": "project",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                },
            },
        )
        print("SETTINGS", settings.status_code)

        turns = [
            "我想把 trainer 做成长期代码教练，但先别写代码，先帮我对齐你会怎么带我。",
            "现在围绕 session restore，帮我压成最小可验证切片，不要替我实现。",
            "下一步给我一个很小的训练动作，要求能验证我是否真的理解这个切片。",
        ]

        for idx, message in enumerate(turns, start=1):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-real-stage2",
                    "intent": "coach",
                    "message": message,
                    "provider": provider_payload,
                    "api_key": API_KEY,
                    "response_language": "zh-CN",
                    "answer_mode": "coach-first",
                },
            )
            payload = response.json()
            coach_turn = payload.get("coach_turn", {})
            memory = payload.get("snapshot", {}).get("memory", {})
            selected_assets = payload.get("snapshot", {}).get("selected_teaching_assets", [])
            print(f"TURN{idx}_STATUS", response.status_code)
            print(f"TURN{idx}_SCENARIO", coach_turn.get("scenario"))
            print(f"TURN{idx}_SUMMARY", (coach_turn.get("summary") or "")[:120])
            print(f"TURN{idx}_NEXT", (coach_turn.get("next_step") or "")[:120])
            print(f"TURN{idx}_ACTIVE_THREAD", ((memory.get("active_thread") or {}).get("focus_area") or ""))
            print(f"TURN{idx}_CURRENT_FOCUS", memory.get("current_focus"))
            print(f"TURN{idx}_DUE_REVIEW_COUNT", memory.get("due_review_count"))
            print(f"TURN{idx}_SELECTED_ASSET_COUNT", len(selected_assets))
            print(
                f"TURN{idx}_REPLY_HEAD",
                (payload.get("reply", {}).get("content") or "")[:220].replace("\n", " "),
            )

        task_next = client.post(
            "/task/next",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-real-stage2",
                "response_language": "zh-CN",
            },
        )
        task_payload = task_next.json()
        print("TASK_NEXT_STATUS", task_next.status_code)
        print("TASK_NEXT_TITLE", task_payload.get("title"))
        print("TASK_NEXT_GOAL", task_payload.get("natural_language_goal"))
    finally:
        client.close()


if __name__ == "__main__":
    main()
