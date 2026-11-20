def composer_conversation_scope(active_view: str | None) -> str:
    """Map a turn's lane marker onto the conversation it belongs to.

    Learning is not a separate conversation any more: the plan, training and
    progress routes are the Chat surface with the learning drawer open, so
    their turns read and write the one coach conversation. The lane marker
    still names the reply format; it no longer splits the history.
    """
    if active_view == "resources":
        return "resources"
    return "coach"
