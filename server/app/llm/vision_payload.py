from __future__ import annotations

from typing import Any


def openai_responses_input_image_parts(*, prompt: str, image_url: str) -> list[dict[str, Any]]:
    """Build the canonical Responses message content for a vision input."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_url},
            ],
        }
    ]
