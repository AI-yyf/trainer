"""P1 #13 (§5): Research becomes the coach's preparation engine.

Guards:
- advance role transitions brief through an injected LLM briefing source,
  with auditable provenance (``briefing_source``: "llm" | "template");
- every briefing failure mode falls back to the fixed template (fail-closed);
- ``collect_research_hints`` consumes background references into bounded
  stage-material hints, degrading to [] when the research lane is empty;
- the stage-material composer surfaces research hints in the LLM prompt only
  when hints exist (prompt unchanged otherwise).
"""

from __future__ import annotations

from typing import Any

from app.pedagogy.research_hints import collect_research_hints
from app.pedagogy.stage_material_composer import StageMaterialComposer
from app.research.briefing import ProviderRoleBriefing
from app.research.models import AgentRole
from app.research.service import ResearchOrchestratorService


class _FakeBriefing:
    def __init__(self, text: str | None = "Next: compare official docs with the saved repo anchor.") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def brief(self, **kwargs: Any) -> str | None:
        self.calls.append(kwargs)
        if self.text is not None and self.text.startswith("raise:"):
            raise RuntimeError(self.text.removeprefix("raise:"))
        return self.text


class _FakeProvider:
    def __init__(self, raw: Any = None, error: Exception | None = None) -> None:
        self._raw = raw
        self._error = error
        self.messages: list[list[dict[str, str]]] = []

    async def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.messages.append(messages)
        if self._error is not None:
            raise self._error
        return self._raw


def _project_with_theme(service: ResearchOrchestratorService) -> tuple[Any, Any]:
    project = service.create_project(title="Preparation", description="coach prep")
    theme = service.add_theme(project.id, title="Attention masks", description="masking in coaching plan")
    assert theme is not None
    service.activate_theme(project.id, theme.id)
    return project, theme


class TestProviderRoleBriefing:
    def test_success_returns_collapsed_text(self) -> None:
        provider = _FakeProvider(raw="  Brief the learner on anchors.  \n")
        briefing = ProviderRoleBriefing(provider)
        text = briefing.brief(
            role=AgentRole.RESEARCHER,
            theme_title="T",
            theme_description="D",
            findings=["f1"],
            language="zh-CN",
        )
        assert text == "Brief the learner on anchors."
        assert provider.messages, "provider must be called"

    def test_blank_reply_falls_back(self) -> None:
        briefing = ProviderRoleBriefing(_FakeProvider(raw="   "))
        assert (
            briefing.brief(
                role=AgentRole.CRITIC,
                theme_title="T",
                theme_description="",
                findings=[],
                language="en-US",
            )
            is None
        )

    def test_provider_error_falls_back(self) -> None:
        briefing = ProviderRoleBriefing(_FakeProvider(error=RuntimeError("no key")))
        assert (
            briefing.brief(
                role=AgentRole.EDITOR,
                theme_title="T",
                theme_description="",
                findings=[],
                language="en-US",
            )
            is None
        )


class TestAdvanceBriefing:
    def test_without_briefing_keeps_template_path(self) -> None:
        service = ResearchOrchestratorService()
        project, theme = _project_with_theme(service)
        result = service.advance_research(project.id, theme_id=theme.id)
        assert result["themes_advanced"][0]["briefing_source"] == "template"
        messages = [m["content"] for m in project.gate.messages if m.get("role") == "agent"]
        assert any("Role: RESEARCHER" in message for message in messages)

    def test_with_briefing_uses_llm_copy(self) -> None:
        service = ResearchOrchestratorService(role_briefing=_FakeBriefing())
        project, theme = _project_with_theme(service)
        thread = service.add_thread(project.id, theme.id, angle="grounding")
        assert thread is not None
        service.add_finding(
            project.id,
            theme.id,
            thread.id,
            content="Tokenizer masks differ from kernel masks.",
            source="docs.example",
            confidence=0.8,
        )
        result = service.advance_research(project.id, theme_id=theme.id)
        assert result["themes_advanced"][0]["briefing_source"] == "llm"
        messages = [m["content"] for m in project.gate.messages if m.get("role") == "agent"]
        assert any("[RESEARCHER] Next: compare official docs" in message for message in messages)

    def test_briefing_failure_falls_back_to_template(self) -> None:
        service = ResearchOrchestratorService(role_briefing=_FakeBriefing("raise:boom"))
        project, theme = _project_with_theme(service)
        result = service.advance_research(project.id, theme_id=theme.id)
        assert result["themes_advanced"][0]["briefing_source"] == "template"

    def test_attach_role_briefing_replaces_source(self) -> None:
        service = ResearchOrchestratorService()
        service.attach_role_briefing(_FakeBriefing())
        project, theme = _project_with_theme(service)
        assert service.advance_research(project.id, theme_id=theme.id)["themes_advanced"][0]["briefing_source"] == "llm"
        service.attach_role_briefing(None)
        project2, theme2 = _project_with_theme(service)
        assert service.advance_research(project2.id, theme_id=theme2.id)["themes_advanced"][0]["briefing_source"] == "template"


class _FakeResearchService:
    def __init__(self, references: list[dict[str, Any]]) -> None:
        self._references = references

    def recent_background_references(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._references)


_REFERENCES = [
    {
        "title": "Attention Is All You Need",
        "source": "https://arxiv.org/abs/1706.03762",
        "snippet": "Self-attention maps a query and key-value pairs...",
        "summary": "Introduces the transformer architecture.",
        "trust_score": 0.9,
        "why_it_matters": "Motivates why mask semantics matter in coaching examples.",
        "source_type": "paper",
    },
    {
        "title": "HF causal masking docs",
        "source": "https://huggingface.co/docs",
        "snippet": "Causal masks prevent attending to future tokens...",
        "summary": "Official docs on causal masking.",
        "trust_score": 0.8,
        "why_it_matters": "Current-practice anchor for the stage material.",
        "source_type": "doc",
    },
]


class TestCollectResearchHints:
    def test_empty_references_yield_no_hints(self) -> None:
        assert (
            collect_research_hints(
                research_service=_FakeResearchService([]),
                workspace_id="ws",
                topic="Attention masks",
            )
            == []
        )

    def test_missing_reader_yields_no_hints(self) -> None:
        assert (
            collect_research_hints(
                research_service=object(),
                workspace_id="ws",
                topic="Attention masks",
            )
            == []
        )

    def test_references_distill_into_bounded_hints(self) -> None:
        hints = collect_research_hints(
            research_service=_FakeResearchService(_REFERENCES),
            workspace_id="ws",
            topic="Attention masks",
        )
        assert hints, "expected distilled hints"
        assert len(hints) <= 8
        assert all(len(hint) <= 220 for hint in hints)
        joined = " ".join(hints)
        assert "Attention Is All You Need" in joined

    def test_hints_are_deduplicated(self) -> None:
        duplicated = _FakeResearchService([*_REFERENCES, *_REFERENCES])
        hints = collect_research_hints(
            research_service=duplicated,
            workspace_id="ws",
            topic="Attention masks",
        )
        assert len(hints) == len({hint.lower() for hint in hints})


class _RecordingComposerProvider:
    def __init__(self) -> None:
        self.seen: list[list[dict[str, str]]] = []

    async def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.seen.append(messages)
        return (
            '{"materials":[{"kind":"study_guide","title":"Guide",'
            '"concept_card":"Grounded content."}]}'
        )


class TestComposerResearchHints:
    async def _compose(self, research_hints: list[str] | None) -> tuple[list[Any], list[list[dict[str, str]]]]:
        provider = _RecordingComposerProvider()
        composer = StageMaterialComposer(provider_service=provider)
        assets = await composer.compose_stage_materials(
            workspace_id="ws",
            plan_title="Plan",
            stage_id="stage-1",
            stage_title="Attention masks",
            stage_goal="Understand masking",
            stage_outcomes=["Outcome"],
            stage_exercises=["Exercise"],
            research_hints=research_hints,
            response_language="en-US",
        )
        return assets, provider.seen

    def test_hints_reach_llm_prompt(self) -> None:
        import asyncio

        assets, seen = asyncio.run(self._compose(["Lane: read the official docs first."]))
        assert assets, "LLM materials should be used when provider succeeds"
        user_prompt = seen[0][1]["content"]
        assert "Background preparation collected for this stage" in user_prompt
        assert "Lane: read the official docs first." in user_prompt

    def test_absent_hints_keep_prompt_unchanged(self) -> None:
        import asyncio

        _assets, seen = asyncio.run(self._compose(None))
        user_prompt = seen[0][1]["content"]
        assert "Background preparation collected for this stage" not in user_prompt
