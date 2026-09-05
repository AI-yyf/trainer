from app.llm.provider_service import _strip_short_cyrillic_noise


def test_strip_short_cyrillic_noise_removes_isolated_token_between_english_words() -> None:
    reply = "Good бк staying tiny and grounded."

    sanitized = _strip_short_cyrillic_noise(
        reply,
        message="Help me keep the first training slice very small.",
    )

    assert sanitized == "Good staying tiny and grounded."


def test_strip_short_cyrillic_noise_removes_short_suffix_inside_english_token() -> None:
    reply = "Once the model clicks, debugging and run confiбн stay more stable."

    sanitized = _strip_short_cyrillic_noise(
        reply,
        message="Help me learn VS Code remote workflows first.",
    )

    assert "бн" not in sanitized
    assert "confi" in sanitized
