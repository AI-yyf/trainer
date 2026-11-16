def composer_conversation_scope(active_view: str | None) -> str:
    if active_view in {"plan", "training", "progress"}:
        return "learning"
    if active_view == "resources":
        return "resources"
    return "coach"
