"""An upstream provider outage is answered as 503, not as a rejected card."""

from __future__ import annotations

from unittest.mock import patch

from app.llm.provider_service import ProviderService
from tests.test_api import build_client

WORKSPACE = "generate-card-provider-outage"


class _GatewayError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"gateway status {status_code}")
        self.status_code = status_code


def _provider_wrapped(status_code: int) -> RuntimeError:
    try:
        try:
            raise _GatewayError(status_code)
        except _GatewayError as cause:
            raise RuntimeError(f"Provider request failed (HTTP {status_code}).") from cause
    except RuntimeError as wrapped:
        return wrapped


def _card_request() -> dict[str, object]:
    return {
        "workspace_id": WORKSPACE,
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": "PPO 裁剪目标",
        "target_skill": "解释 PPO clip 目标并手写损失函数",
        "provider": {
            "name": "outage-probe",
            "baseUrl": "http://127.0.0.1:9",
            "apiKeyRef": "outage-probe",
            "model": "MiniMax-M3.1-Flash",
            "protocol": "openai_chat_completions_compatible",
        },
        "api_key": "sk-test-never-sent",
        "response_language": "en-US",
    }


def test_provider_outage_returns_503_with_retry_after(tmp_path) -> None:
    with build_client(tmp_path) as client:
        with patch.object(ProviderService, "chat_completion", side_effect=_provider_wrapped(502)):
            response = client.post("/training/generate-card", json=_card_request())

    assert response.status_code == 503, response.text
    assert response.headers.get("retry-after") == "5"
    detail = response.json()["detail"]
    assert "temporarily unavailable" in detail
    assert "not accepted" not in detail


def test_quota_exhaustion_returns_402(tmp_path) -> None:
    with build_client(tmp_path) as client:
        with patch.object(ProviderService, "chat_completion", side_effect=_provider_wrapped(402)):
            response = client.post("/training/generate-card", json=_card_request())

    assert response.status_code == 402, response.text
    assert "quota" in response.json()["detail"]
