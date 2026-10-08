from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import fitz
import pytest

from app.core.models import CapabilityFlags, ProviderConfig
from app.llm.provider_service import ProviderService
from app.llm.vision_challenge import build_vision_challenge


def test_challenge_is_decodable_content_and_does_not_disclose_the_answer() -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69]):
        challenge = build_vision_challenge()
    image = fitz.Pixmap(base64.b64decode(challenge.image_url.split(",")[1]))
    assert (image.width, image.height) == (384, 128)
    assert challenge.expected == ("41", "26", "79")
    assert all(number not in challenge.prompt for number in challenge.expected)
    assert challenge.matches('{"left":"41","middle":"26","right":"79"}')
    # The bitmap has actual black digit strokes and white holes, not a single
    # colored pixel with a yes/no marker that a text-only model can echo.
    assert image.pixel(24, 39)[:3] == (18, 18, 18)
    assert image.pixel(24 + 7, 39)[:3] == (255, 255, 255)


@pytest.mark.parametrize("answer", [
    "VISION_OK", "Yes VISION_OK", "UNKNOWN", "41,26,79",
    '{"left":"41","middle":"26","right":"78"}',
    '{"left":41,"middle":26,"right":79}',
    '{"left":"41","middle":"26","right":"79","extra":"ok"}',
    'The answer is {"left":"41","middle":"26","right":"79"}',
])
def test_marker_guess_and_partially_matching_content_never_verify(answer: str) -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69]):
        challenge = build_vision_challenge()
    assert not challenge.matches(answer)


def test_replayed_visual_answer_does_not_verify_a_new_challenge() -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69, 54, 35, 82]):
        first, second = build_vision_challenge(), build_vision_challenge()
    answer = json.dumps(dict(zip(("left", "middle", "right"), first.expected, strict=True)))
    assert first.matches(answer)
    assert not second.matches(answer)
    assert first.image_url != second.image_url


@pytest.mark.parametrize("fence", ["json", "JSON", ""])
def test_single_json_code_block_verifies_the_same_visible_content(fence: str) -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69]):
        challenge = build_vision_challenge()
    answer = '{"left":"41","middle":"26","right":"79"}'
    assert challenge.matches(f"```{fence}\n{answer}\n```")
    assert not challenge.matches(f"```{fence}\n{answer}\n```\nI guessed.")
    assert not challenge.matches(f"I guessed.\n```{fence}\n{answer}\n```")
    assert not challenge.matches(f"```{fence}\n{answer.replace('79', '78')}\n```")


def test_live_probe_path_rejects_an_echoed_marker() -> None:
    service = ProviderService()
    provider = ProviderConfig(
        name="visual-check", base_url="https://example.invalid/v1", model="model",
        api_key_ref="test", protocol="openai_responses",
        capabilities=CapabilityFlags(responses=True, vision=True),
    )
    client = MagicMock()
    client.responses.create.return_value = {"output_text": "VISION_OK"}
    with patch.object(service, "_create_sync_client", return_value=client):
        observed, diagnostic = service._probe_vision_capability(provider, "test-secret")
    assert observed is False
    assert "randomized image content" in diagnostic
    assert "test-secret" not in diagnostic
