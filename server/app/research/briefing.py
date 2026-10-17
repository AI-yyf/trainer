"""LLM role briefings for the research advance loop (P1 #13, §5).

Research's product identity is the coach's preparation room: ``advance`` must
produce real, grounded role briefings instead of fixed templates whenever a
provider is available. The orchestrator only knows the ``ResearchRoleBriefing``
Protocol — this module owns the ProviderService adapter and the fail-closed
rule that *any* provider failure falls back to the existing templates, so a
network or credential problem can never block the advance loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from .models import AgentRole

logger = logging.getLogger(__name__)


class ResearchRoleBriefing(Protocol):
    """One-shot, synchronous briefing call. Return ``None`` to fall back."""

    def brief(
        self,
        *,
        role: AgentRole,
        theme_title: str,
        theme_description: str,
        findings: list[str],
        language: str,
    ) -> str | None: ...


_ROLE_FOCUS: dict[AgentRole, str] = {
    AgentRole.RESEARCHER: (
        "Gather and deepen material: name the most promising next sources, "
        "search angles, or open questions for this theme."
    ),
    AgentRole.EDITOR: (
        "Organize what is known: propose the coherent structure the collected "
        "findings should be arranged into for teaching."
    ),
    AgentRole.CRITIC: (
        "Critique what is known: name gaps, inconsistencies, or weak claims in "
        "the collected findings, and what would resolve them."
    ),
    AgentRole.SYNTHESIZER: (
        "Synthesize: draft the takeaway summary a coach could turn into stage "
        "materials, and what still needs human approval."
    ),
}


class ProviderRoleBriefing:
    """Adapter over ``ProviderService.chat_completion`` (the coach pipeline).

    Every failure mode — missing key, network error, blank reply, or a call
    from inside a running event loop — returns ``None`` so the orchestrator
    keeps its deterministic template path. Briefings are advisory copy for
    the research gate; they never gate the state machine.
    """

    def __init__(self, provider_service: Any) -> None:
        self._provider = provider_service

    def brief(
        self,
        *,
        role: AgentRole,
        theme_title: str,
        theme_description: str,
        findings: list[str],
        language: str,
    ) -> str | None:
        focus = _ROLE_FOCUS.get(role, "Continue the current research phase.")
        findings_block = "\n".join(f"- {item}" for item in findings[:5]) or "- (no findings yet)"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the research preparation engine inside a coaching "
                    "tool. Write one short briefing (at most 120 words) for the "
                    f"{role.upper()} phase of a preparation theme. Be concrete "
                    "and cite the given findings; never invent sources."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Theme: {theme_title}\n"
                    f"Description: {theme_description or '(not provided)'}\n"
                    f"Collected findings:\n{findings_block}\n\n"
                    f"Task: {focus}\n"
                    f"Write the briefing in the learner's response language ({language})."
                ),
            },
        ]
        try:
            raw = asyncio.run(
                self._provider.chat_completion(messages, temperature=0.4, max_tokens=400)
            )
        except RuntimeError:
            # A running event loop means we were called from async context;
            # fail closed instead of nesting loops.
            logger.warning("research briefing skipped: running event loop")
            return None
        except Exception:
            logger.warning("research briefing failed", exc_info=True)
            return None
        text = " ".join(str(raw or "").split()).strip()
        return text[:900] or None
