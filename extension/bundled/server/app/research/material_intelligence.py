from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True)
class MaterialBundle:
    topic: str
    topic_family: str
    scenario: str
    material_summary: str
    current_practices: list[str] = field(default_factory=list)
    implementation_patterns: list[str] = field(default_factory=list)
    interesting_research_angles: list[str] = field(default_factory=list)
    project_anchors: list[str] = field(default_factory=list)
    exercise_candidates: list[str] = field(default_factory=list)
    review_rhythm_candidates: list[str] = field(default_factory=list)
    implementation_surfaces: list[str] = field(default_factory=list)
    code_anchor_questions: list[str] = field(default_factory=list)
    focus_questions: list[str] = field(default_factory=list)
    paper_candidates: list[dict[str, Any]] = field(default_factory=list)
    repo_candidates: list[dict[str, Any]] = field(default_factory=list)
    doc_candidates: list[dict[str, Any]] = field(default_factory=list)
    source_lanes: list[str] = field(default_factory=list)
    implementation_claims: list[str] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    source_breakdown: dict[str, Any] = field(default_factory=dict)
    material_highlights: list[str] = field(default_factory=list)
    teaching_sequence: list[str] = field(default_factory=list)
    should_use: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MaterialIntelligenceService:
    def build_material_bundle(
        self,
        *,
        topic: str,
        topic_family: str,
        scenario: str,
        blueprint: dict[str, Any],
        grounding_references: list[dict[str, object]] | None = None,
        discovered_references: list[dict[str, object]] | None = None,
        weekly_hours: int = 4,
    ) -> MaterialBundle:
        enriched = self.enrich_brief(
            topic=topic,
            topic_family=topic_family,
            scenario=scenario,
            blueprint=blueprint,
            grounding_references=grounding_references,
            discovered_references=discovered_references,
            weekly_hours=weekly_hours,
        )
        return MaterialBundle(
            topic=str(enriched.get("topic", topic) or topic).strip() or topic,
            topic_family=str(enriched.get("topic_family", topic_family) or topic_family).strip() or topic_family,
            scenario=str(enriched.get("scenario", scenario) or scenario).strip() or scenario,
            material_summary=str(enriched.get("material_summary") or "").strip(),
            current_practices=self._brief_strings(enriched.get("current_practices"), limit=5),
            implementation_patterns=self._brief_strings(enriched.get("implementation_patterns"), limit=5),
            interesting_research_angles=self._brief_strings(enriched.get("interesting_research_angles"), limit=5),
            project_anchors=self._brief_strings(enriched.get("project_anchors"), limit=5),
            exercise_candidates=self._brief_strings(enriched.get("exercise_candidates"), limit=5),
            review_rhythm_candidates=self._brief_strings(enriched.get("review_rhythm_candidates"), limit=4),
            implementation_surfaces=self._brief_strings(enriched.get("implementation_surfaces"), limit=5),
            code_anchor_questions=self._brief_strings(enriched.get("code_anchor_questions"), limit=4),
            focus_questions=self._brief_strings(enriched.get("focus_questions"), limit=7),
            paper_candidates=[item for item in enriched.get("paper_candidates", []) if isinstance(item, dict)],
            repo_candidates=[item for item in enriched.get("repo_candidates", []) if isinstance(item, dict)],
            doc_candidates=[item for item in enriched.get("doc_candidates", []) if isinstance(item, dict)],
            source_lanes=self._brief_strings(enriched.get("source_lanes"), limit=4),
            implementation_claims=self._brief_strings(enriched.get("implementation_claims"), limit=5),
            references=[item for item in enriched.get("references", []) if isinstance(item, dict)],
            source_breakdown=dict(enriched.get("source_breakdown") or {}),
            material_highlights=self._brief_strings(enriched.get("material_highlights"), limit=3),
            teaching_sequence=self._brief_strings(enriched.get("teaching_sequence"), limit=5),
            should_use=bool(
                enriched.get("should_use")
                or enriched.get("references")
                or enriched.get("paper_candidates")
                or enriched.get("repo_candidates")
                or enriched.get("source_lanes")
                or enriched.get("implementation_claims")
                or enriched.get("focus_questions")
            ),
        )

    def enrich_brief(
        self,
        *,
        topic: str,
        topic_family: str,
        scenario: str,
        blueprint: dict[str, Any],
        grounding_references: list[dict[str, object]] | None = None,
        discovered_references: list[dict[str, object]] | None = None,
        weekly_hours: int = 4,
    ) -> dict[str, Any]:
        normalized_grounding = self._normalize_references(
            grounding_references or [],
            default_origin="grounding_material",
        )
        normalized_discovered = self._normalize_references(
            discovered_references or [],
            default_origin="discovered_reference",
        )
        combined_references = self._dedupe_references(
            [*normalized_grounding, *normalized_discovered],
            limit=10,
        )
        paper_candidates = self._candidate_payloads(
            combined_references,
            kind="paper",
            limit=3,
        )
        repo_candidates = self._candidate_payloads(
            combined_references,
            kind="repo",
            limit=3,
        )
        doc_candidates = self._candidate_payloads(
            combined_references,
            kind="doc",
            limit=3,
        )
        if not paper_candidates and doc_candidates:
            paper_candidates = [
                {
                    "title": doc_candidates[0]["title"],
                    "source": doc_candidates[0]["source"],
                    "snippet": doc_candidates[0]["snippet"],
                    "summary": doc_candidates[0]["summary"],
                    "trust_score": doc_candidates[0]["trust_score"],
                    "why_it_matters": doc_candidates[0]["why_it_matters"],
                }
            ]
        if not repo_candidates:
            repo_candidates = self._fallback_repo_candidates(
                topic=topic,
                doc_candidates=doc_candidates,
                paper_candidates=paper_candidates,
                references=combined_references,
            )
        implementation_claims = self._implementation_claims(
            combined_references,
            limit=5,
        )
        material_topic_map = self._material_topic_map(
            topic=topic,
            topic_family=topic_family,
            blueprint=blueprint,
            references=combined_references,
        )
        current_practices = self._merge_strings(
            blueprint.get("current_practices"),
            self._derived_current_practices(
                topic=topic,
                topic_family=topic_family,
                doc_candidates=doc_candidates,
                implementation_claims=implementation_claims,
            ),
            limit=5,
        )
        implementation_patterns = self._merge_strings(
            blueprint.get("implementation_patterns"),
            self._derived_implementation_patterns(
                topic_family=topic_family,
                repo_candidates=repo_candidates,
                implementation_claims=implementation_claims,
                weekly_hours=weekly_hours,
            ),
            limit=5,
        )
        interesting_research_angles = self._merge_strings(
            blueprint.get("interesting_research_angles"),
            self._derived_research_angles(
                topic=topic,
                paper_candidates=paper_candidates,
                repo_candidates=repo_candidates,
                implementation_claims=implementation_claims,
            ),
            limit=5,
        )
        project_anchors = self._merge_strings(
            blueprint.get("project_anchors"),
            self._derived_project_anchors(
                topic=topic,
                repo_candidates=repo_candidates,
                paper_candidates=paper_candidates,
            ),
            limit=5,
        )
        exercise_candidates = self._merge_strings(
            blueprint.get("exercise_candidates"),
            self._derived_exercises(
                topic=topic,
                repo_candidates=repo_candidates,
                implementation_claims=implementation_claims,
                paper_candidates=paper_candidates,
            ),
            limit=5,
        )
        review_rhythm_candidates = self._merge_strings(
            blueprint.get("review_rhythm_candidates"),
            self._derived_review_rhythm(
                topic=topic,
                implementation_claims=implementation_claims,
                paper_candidates=paper_candidates,
            ),
            limit=4,
        )
        implementation_surfaces = self._merge_strings(
            blueprint.get("implementation_surfaces"),
            self._derived_implementation_surfaces(
                topic=topic,
                repo_candidates=repo_candidates,
                paper_candidates=paper_candidates,
            ),
            limit=5,
        )
        code_anchor_questions = self._merge_strings(
            blueprint.get("code_anchor_questions"),
            self._derived_code_anchor_questions(
                topic=topic,
                topic_family=topic_family,
                implementation_claims=implementation_claims,
            ),
            limit=4,
        )
        open_questions = self._merge_strings(
            blueprint.get("focus_questions"),
            self._derived_open_questions(
                topic=topic,
                topic_family=topic_family,
                paper_candidates=paper_candidates,
                repo_candidates=repo_candidates,
                implementation_claims=implementation_claims,
            ),
            limit=7,
        )
        source_lanes = self._source_lanes(
            topic=topic,
            paper_candidates=paper_candidates,
            repo_candidates=repo_candidates,
            doc_candidates=doc_candidates,
        )
        material_summary = self._material_summary(
            topic=topic,
            scenario=scenario,
            paper_candidates=paper_candidates,
            repo_candidates=repo_candidates,
            implementation_claims=implementation_claims,
        )
        teaching_sequence = self._teaching_sequence(
            topic=topic,
            topic_family=topic_family,
            scenario=scenario,
            current_practices=current_practices,
            implementation_patterns=implementation_patterns,
            interesting_research_angles=interesting_research_angles,
            project_anchors=project_anchors,
            exercise_candidates=exercise_candidates,
            review_rhythm_candidates=review_rhythm_candidates,
            implementation_surfaces=implementation_surfaces,
            code_anchor_questions=code_anchor_questions,
            focus_questions=open_questions,
            paper_candidates=paper_candidates,
            repo_candidates=repo_candidates,
        )
        return {
            "topic": topic,
            "topic_family": topic_family,
            "scenario": scenario,
            "topic_map": material_topic_map,
            "material_summary": material_summary,
            "material_highlights": [
                item["snippet"]
                for item in combined_references[:3]
                if str(item.get("snippet", "")).strip()
            ],
            "implementation_claims": implementation_claims,
            "current_practices": current_practices,
            "implementation_patterns": implementation_patterns,
            "interesting_research_angles": interesting_research_angles,
            "project_anchors": project_anchors,
            "exercise_candidates": exercise_candidates,
            "review_rhythm_candidates": review_rhythm_candidates,
            "implementation_surfaces": implementation_surfaces,
            "code_anchor_questions": code_anchor_questions,
            "focus_questions": open_questions,
            "teaching_sequence": teaching_sequence,
            "paper_candidates": paper_candidates,
            "repo_candidates": repo_candidates,
            "source_lanes": source_lanes,
            "source_breakdown": self._source_breakdown(combined_references),
            "references": combined_references[:6],
            "material_bundle": MaterialBundle(
                topic=topic,
                topic_family=topic_family,
                scenario=scenario,
                material_summary=material_summary,
                current_practices=current_practices,
                implementation_patterns=implementation_patterns,
                interesting_research_angles=interesting_research_angles,
                project_anchors=project_anchors,
                exercise_candidates=exercise_candidates,
                review_rhythm_candidates=review_rhythm_candidates,
                implementation_surfaces=implementation_surfaces,
                code_anchor_questions=code_anchor_questions,
                focus_questions=open_questions,
                paper_candidates=paper_candidates,
                repo_candidates=repo_candidates,
                doc_candidates=doc_candidates,
                source_lanes=source_lanes,
                implementation_claims=implementation_claims,
                references=combined_references[:6],
                source_breakdown=self._source_breakdown(combined_references),
                material_highlights=[
                    item["snippet"]
                    for item in combined_references[:3]
                    if str(item.get("snippet", "")).strip()
                ],
                teaching_sequence=teaching_sequence,
                should_use=bool(
                    combined_references
                    or source_lanes
                    or implementation_claims
                    or paper_candidates
                    or repo_candidates
                    or open_questions
                ),
            ).to_dict(),
        }

    def _brief_strings(self, value: object, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for raw in value:
            text = str(raw or "").strip()
            if text and text not in items:
                items.append(text)
            if len(items) >= limit:
                break
        return items

    def _normalize_references(
        self,
        items: list[dict[str, object]],
        *,
        default_origin: str,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            snippet = self._compact(item.get("snippet"), max_chars=220)
            source = self._compact(item.get("source"), max_chars=240)
            title = self._compact(
                item.get("title") or item.get("focus_area") or item.get("summary") or source,
                max_chars=140,
            )
            if not snippet and not title:
                continue
            source_type = self._compact(item.get("source_type"), max_chars=48) or "reference"
            raw_trust_score = item.get("trust_score", 0.0)
            trust_score = (
                float(raw_trust_score or 0.0)
                if isinstance(raw_trust_score, (int, float, str))
                else 0.0
            )
            raw_quality_flags = item.get("quality_flags")
            quality_flags = (
                [str(flag).strip() for flag in raw_quality_flags if str(flag).strip()]
                if isinstance(raw_quality_flags, list)
                else []
            )
            normalized.append(
                {
                    "title": title or "Reference",
                    "source": source,
                    "snippet": snippet or title,
                    "summary": self._compact(item.get("summary") or snippet or title, max_chars=110),
                    "source_type": source_type,
                    "trust_score": trust_score,
                    "freshness": self._compact(item.get("freshness"), max_chars=24) or "unknown",
                    "why_it_matters": self._compact(item.get("why_it_matters"), max_chars=180),
                    "origin": self._compact(item.get("reference_origin"), max_chars=48) or default_origin,
                    "kind": self._reference_kind(source=source, title=title, source_type=source_type, snippet=snippet),
                    "quality_flags": quality_flags,
                    "pdf_url": self._paper_pdf_url(source),
                }
            )
        return normalized

    def _reference_kind(
        self,
        *,
        source: str,
        title: str,
        source_type: str,
        snippet: str,
    ) -> str:
        lowered = " ".join([source, title, source_type, snippet]).lower()
        domain = (urlparse(source).netloc or "").lower()
        if any(
            token in lowered
            for token in (
                "arxiv",
                "openreview",
                "paper",
                "论文",
                "acl anthology",
                "proceedings.mlr",
                ".pdf",
                "doi.org",
            )
        ) or domain in {
            "arxiv.org",
            "openreview.net",
            "aclanthology.org",
            "proceedings.mlr.press",
            "doi.org",
        }:
            return "paper"
        if any(
            token in lowered
            for token in ("github", "gitlab", "repo", "repository", "source code", "implementation")
        ) or domain in {"github.com", "gitlab.com", "huggingface.co"}:
            return "repo"
        if any(
            token in lowered
            for token in ("docs", "documentation", "reference", "api", "official docs")
        ) or domain.startswith("docs.") or "readthedocs" in domain:
            return "doc"
        return "reference"

    def _paper_pdf_url(self, source: str) -> str:
        if "arxiv.org/abs/" in source:
            return source.replace("/abs/", "/pdf/") + ".pdf"
        if source.endswith(".pdf"):
            return source
        return ""

    def _candidate_payloads(
        self,
        references: list[dict[str, Any]],
        *,
        kind: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        candidates = [item for item in references if item.get("kind") == kind]
        ranked = sorted(
            candidates,
            key=lambda item: (
                -float(item.get("trust_score", 0.0) or 0.0),
                item.get("freshness") != "fresh",
                item.get("title", ""),
            ),
        )
        payloads: list[dict[str, Any]] = []
        for item in ranked[:limit]:
            payload = {
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "snippet": item.get("snippet", ""),
                "summary": item.get("summary", ""),
                "trust_score": item.get("trust_score", 0.0),
                "why_it_matters": item.get("why_it_matters", ""),
            }
            if kind == "paper" and item.get("pdf_url"):
                payload["pdf_url"] = item.get("pdf_url")
            payloads.append(payload)
        return payloads

    def _material_topic_map(
        self,
        *,
        topic: str,
        topic_family: str,
        blueprint: dict[str, Any],
        references: list[dict[str, Any]],
    ) -> list[str]:
        starter = self._merge_strings(blueprint.get("topic_map"), [], limit=4)
        if starter:
            return starter
        if "mask" in f"{topic} {topic_family}".lower() or "attention" in f"{topic} {topic_family}".lower():
            return [
                "Mask semantics: who can see whom, and whether the effect is hard blocking or score biasing.",
                "Library boundary: tokenizer-side masks, model-side causal masks, and kernel-level attention masks are different surfaces.",
                "Runtime boundary: cache-aware generation, packed batches, and optimized kernels change how masks are expressed.",
                "Variant boundary: VLM and VLA sequences stop behaving exactly like plain text-only attention.",
            ]
        top_reference = references[0]["title"] if references else topic
        return [
            f"Core mechanism for {topic}.",
            f"Real API or code path that exposes {topic}.",
            f"Verification seam that shows whether {topic} actually worked in code.",
            f"Modern variant or adjacent case that changes the shape of {topic}: {top_reference}.",
        ]

    def _implementation_claims(
        self,
        references: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[str]:
        claims: list[str] = []
        for item in references:
            for sentence in self._sentences(str(item.get("snippet", "") or "")):
                if not self._looks_like_implementation_sentence(sentence):
                    continue
                claims.append(sentence)
        if not claims:
            for item in references:
                kind = str(item.get("kind", "") or "").strip()
                snippet = self._compact(item.get("snippet"), max_chars=220)
                title = self._compact(item.get("title"), max_chars=120)
                if kind == "repo" and snippet:
                    claims.append(f"{title}: {snippet}".strip(": "))
                elif kind == "paper" and snippet:
                    claims.append(f"{title}: {snippet}".strip(": "))
        return self._dedupe_strings(claims, limit=limit)

    def _derived_current_practices(
        self,
        *,
        topic: str,
        topic_family: str,
        doc_candidates: list[dict[str, Any]],
        implementation_claims: list[str],
    ) -> list[str]:
        practices: list[str] = []
        if doc_candidates:
            practices.append(
                f"Anchor {topic or 'the topic'} in current official docs before widening into older paper-era abstractions."
            )
        if implementation_claims:
            practices.append(
                f"Teach {topic or 'the topic'} through one real implementation seam, not only through static theory."
            )
        if "mask" in f"{topic} {topic_family}".lower() or "attention" in f"{topic} {topic_family}".lower():
            practices.append(
                "Separate tokenizer masks, model-side masks, and kernel/runtime masks so the learner does not collapse them into one idea."
            )
        return self._dedupe_strings(practices, limit=4)

    def _derived_implementation_patterns(
        self,
        *,
        topic_family: str,
        repo_candidates: list[dict[str, Any]],
        implementation_claims: list[str],
        weekly_hours: int,
    ) -> list[str]:
        patterns: list[str] = []
        if repo_candidates:
            patterns.append(
                "Start from one visible repo path and keep the first exercise inside a single file or module boundary."
            )
        if implementation_claims:
            patterns.append(
                "Turn the strongest implementation claim into a code-reading step first, then into a tiny learner-owned slice or reproduction."
            )
        if weekly_hours <= 4:
            patterns.append(
                "Keep the first drill slice-sized so the learner can verify one behavior before widening scope."
            )
        if "attention" in topic_family or "mask" in topic_family:
            patterns.append(
                "Compare two adjacent mask behaviors in the same script so the abstraction change is visible."
            )
        return self._dedupe_strings(patterns, limit=4)

    def _derived_research_angles(
        self,
        *,
        topic: str,
        paper_candidates: list[dict[str, Any]],
        repo_candidates: list[dict[str, Any]],
        implementation_claims: list[str],
    ) -> list[str]:
        angles: list[str] = []
        if paper_candidates:
            angles.append(
                f"Trace how recent papers about {topic or 'the topic'} differ from current library defaults."
            )
        if repo_candidates:
            angles.append(
                "Compare paper claims with the real implementation shortcuts or compromises visible in current repos."
            )
        if implementation_claims:
            angles.append(
                "Turn one saved implementation claim into a hypothesis, then verify it against code instead of trusting the summary blindly."
            )
        return self._dedupe_strings(angles, limit=4)

    def _derived_project_anchors(
        self,
        *,
        topic: str,
        repo_candidates: list[dict[str, Any]],
        paper_candidates: list[dict[str, Any]],
    ) -> list[str]:
        anchors: list[str] = []
        if repo_candidates:
            first_repo = repo_candidates[0]
            anchors.append(
                f"Use '{first_repo['title']}' as a concrete code-reading anchor for {topic or 'the topic'}."
            )
        if paper_candidates:
            first_paper = paper_candidates[0]
            anchors.append(
                f"Use '{first_paper['title']}' as the explanation anchor that motivates why the implementation exists."
            )
        return self._dedupe_strings(anchors, limit=4)

    def _derived_exercises(
        self,
        *,
        topic: str,
        repo_candidates: list[dict[str, Any]],
        implementation_claims: list[str],
        paper_candidates: list[dict[str, Any]],
    ) -> list[str]:
        exercises: list[str] = []
        if implementation_claims:
            exercises.append(
                f"Pick one implementation claim about {topic or 'the topic'}, recreate the smallest reproducible version locally, then explain what changed."
            )
        if repo_candidates:
            exercises.append(
                f"Read one narrow repo path, annotate where {topic or 'the topic'} first becomes concrete, then implement or reproduce that seam as a tiny self-owned slice."
            )
        if paper_candidates:
            exercises.append(
                "Summarize one paper method in plain language, then map it to the closest code path or API surface you can actually inspect."
            )
        return self._dedupe_strings(exercises, limit=4)

    def _derived_review_rhythm(
        self,
        *,
        topic: str,
        implementation_claims: list[str],
        paper_candidates: list[dict[str, Any]],
    ) -> list[str]:
        review_points: list[str] = []
        if implementation_claims:
            review_points.append(
                f"After each drill, restate which implementation claim about {topic or 'the topic'} was verified and which was still only assumed."
            )
        if paper_candidates:
            review_points.append(
                "Do one later review that compares the saved paper idea with the actual implementation compromise found in code."
            )
        return self._dedupe_strings(review_points, limit=3)

    def _derived_implementation_surfaces(
        self,
        *,
        topic: str,
        repo_candidates: list[dict[str, Any]],
        paper_candidates: list[dict[str, Any]],
    ) -> list[str]:
        surfaces: list[str] = []
        if repo_candidates:
            surfaces.append("Reference repo surface")
        if paper_candidates:
            surfaces.append("Paper-to-code translation surface")
        surfaces.append(f"Workspace implementation surface for {topic or 'the topic'}")
        return self._dedupe_strings(surfaces, limit=4)

    def _derived_code_anchor_questions(
        self,
        *,
        topic: str,
        topic_family: str,
        implementation_claims: list[str],
    ) -> list[str]:
        questions: list[str] = []
        if "mask" in f"{topic} {topic_family}".lower() or "attention" in f"{topic} {topic_family}".lower():
            questions.extend(
                [
                    "Where does the mask first become concrete in code: tokenizer, model, or kernel?",
                    "Which runtime path changes once cache-aware generation or multimodal tokens enter the sequence?",
                ]
            )
        if implementation_claims:
            questions.append(
                f"Which line or function is the smallest trustworthy code anchor for {topic or 'the topic'}?"
            )
        return self._dedupe_strings(questions, limit=4)

    def _derived_open_questions(
        self,
        *,
        topic: str,
        topic_family: str,
        paper_candidates: list[dict[str, Any]],
        repo_candidates: list[dict[str, Any]],
        implementation_claims: list[str],
    ) -> list[str]:
        questions: list[str] = []
        if not paper_candidates:
            questions.append(
                f"Which recent paper best changes the implementation story for {topic or 'this topic'}?"
            )
        if not repo_candidates:
            questions.append(
                f"Which current repo shows {topic or 'this topic'} cleanly enough to turn into a teaching exercise?"
            )
        if implementation_claims:
            questions.append(
                "Which claims are grounded in saved material, and which still need direct code verification?"
            )
        lowered = f"{topic} {topic_family}".lower()
        material_text = " ".join(
            [
                topic,
                topic_family,
                " ".join(item.get("title", "") for item in paper_candidates if isinstance(item, dict)),
                " ".join(item.get("title", "") for item in repo_candidates if isinstance(item, dict)),
                " ".join(implementation_claims),
            ]
        ).lower()
        if "vlm" in lowered or "vla" in lowered or "vlm" in material_text or "vla" in material_text or "multimodal" in material_text or "action" in material_text:
            questions.extend(
                [
                    "What breaks once VLM or VLA tokens enter the sequence boundary?",
                    "Which part is still text masking, and which part becomes VLM/VLA-specific?",
                ]
            )
        if "mask" in lowered or "attention" in lowered or "mask" in material_text or "attention" in material_text:
            questions.extend(
                [
                    "Where does the mask first become concrete in code: tokenizer, model, or kernel?",
                    "What changes in cache-aware generation or packed batches?",
                    "How does the same masking idea change in VLM and VLA variants?",
                    "How do VLM/VLA variants change the mask story compared with plain text attention?",
                ]
            )
        return self._dedupe_strings(questions, limit=7)

    def _fallback_repo_candidates(
        self,
        *,
        topic: str,
        doc_candidates: list[dict[str, Any]],
        paper_candidates: list[dict[str, Any]],
        references: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        anchor = doc_candidates[0] if doc_candidates else (paper_candidates[0] if paper_candidates else None)
        if not isinstance(anchor, dict) and references:
            anchor = references[0]
        if not isinstance(anchor, dict):
            return []
        title = str(anchor.get("title") or topic or "Code anchor").strip()
        source = str(anchor.get("source") or "").strip()
        snippet = str(anchor.get("snippet") or anchor.get("summary") or "").strip()
        if not (title or source or snippet):
            return []
        return [
            {
                "title": f"{title} code anchor",
                "source": source,
                "snippet": snippet or f"Use this as the nearest code-reading anchor for {topic or 'the topic'}.",
                "summary": anchor.get("summary") or snippet or title,
                "trust_score": float(anchor.get("trust_score", 0.0) or 0.0),
                "why_it_matters": anchor.get("why_it_matters")
                or f"Use this as the nearest code-reading anchor for {topic or 'the topic'}.",
            }
        ]

    def _source_lanes(
        self,
        *,
        topic: str,
        paper_candidates: list[dict[str, Any]],
        repo_candidates: list[dict[str, Any]],
        doc_candidates: list[dict[str, Any]],
    ) -> list[str]:
        lanes: list[str] = []
        if doc_candidates:
            lanes.append(
                f"Current practice lane: start with {doc_candidates[0]['title']}, then verify the live API surface."
            )
        if paper_candidates and repo_candidates:
            lanes.append(
                f"Paper-to-code lane: read {paper_candidates[0]['title']} and then inspect {repo_candidates[0]['title']}."
            )
        elif repo_candidates:
            lanes.append(
                f"Implementation lane: use {repo_candidates[0]['title']} as the first code anchor for {topic or 'the topic'}."
            )
        elif paper_candidates:
            lanes.append(
                f"Explanation lane: use {paper_candidates[0]['title']} to motivate why the implementation matters."
            )
        return self._dedupe_strings(lanes, limit=3)

    def _material_summary(
        self,
        *,
        topic: str,
        scenario: str,
        paper_candidates: list[dict[str, Any]],
        repo_candidates: list[dict[str, Any]],
        implementation_claims: list[str],
    ) -> str:
        clauses: list[str] = []
        if topic:
            clauses.append(f"Ground the coaching loop around {topic}.")
        if paper_candidates:
            clauses.append(f"Recent papers found: {paper_candidates[0]['title']}.")
        if repo_candidates:
            clauses.append(f"Code anchor found: {repo_candidates[0]['title']}.")
        if implementation_claims:
            clauses.append(f"Saved implementation signals: {implementation_claims[0]}")
        if scenario:
            clauses.append(f"Use them in a {scenario} teaching flow.")
        return " ".join(clause.strip() for clause in clauses if clause.strip())

    def _teaching_sequence(
        self,
        *,
        topic: str,
        topic_family: str,
        scenario: str,
        current_practices: list[str],
        implementation_patterns: list[str],
        interesting_research_angles: list[str],
        project_anchors: list[str],
        exercise_candidates: list[str],
        review_rhythm_candidates: list[str],
        implementation_surfaces: list[str],
        code_anchor_questions: list[str],
        focus_questions: list[str],
        paper_candidates: list[dict[str, Any]],
        repo_candidates: list[dict[str, Any]],
    ) -> list[str]:
        sequence: list[str] = []
        if topic:
            sequence.append(f"先把主题收窄到：{topic}。")
        if current_practices:
            sequence.append(f"先讲当前实践主线：{current_practices[0]}。")
        if paper_candidates:
            sequence.append(f"再用论文线索打开动机：{paper_candidates[0]['title']}。")
        if repo_candidates:
            sequence.append(f"随后切到代码锚点：{repo_candidates[0]['title']}。")
        if implementation_patterns:
            sequence.append(f"把实现模式压成第一步：{implementation_patterns[0]}。")
        if code_anchor_questions:
            sequence.append(f"先回答第一个代码锚点问题：{code_anchor_questions[0]}。")
        if implementation_surfaces:
            sequence.append(f"然后落到实现面：{implementation_surfaces[0]}。")
        if exercise_candidates:
            sequence.append(f"再用一道训练题收口：{exercise_candidates[0]}。")
        if review_rhythm_candidates:
            sequence.append(f"复习节奏先定成：{review_rhythm_candidates[0]}。")
        if focus_questions:
            sequence.append(f"保留一个追问：{focus_questions[0]}。")
        if scenario and scenario not in {"general", "guided"}:
            sequence.append(f"这条序列按 {scenario} 场景讲。")
        if topic_family and topic_family not in {"general", "unknown"}:
            sequence.append(f"讲解时显式区分 {topic_family} 这条主线。")
        if project_anchors:
            sequence.append(f"额外保留一个项目锚点：{project_anchors[0]}。")
        if interesting_research_angles:
            sequence.append(f"补一个研究角度：{interesting_research_angles[0]}。")
        if not sequence:
            sequence.extend(
                [
                    "先从最稳定的一个材料切口开始讲。",
                    "先讲这个切口为什么重要。",
                    "再把它映射到一个具体代码位置。",
                    "最后用一个最小练习验证它。",
                ]
            )
        return self._dedupe_strings(sequence, limit=10)

    def _source_breakdown(self, references: list[dict[str, Any]]) -> dict[str, Any]:
        source_counter = Counter(str(item.get("source_type", "reference")) for item in references)
        kind_counter = Counter(str(item.get("kind", "reference")) for item in references)
        top_sources: list[str] = []
        seen_sources: set[str] = set()
        for item in references:
            source = str(item.get("source", "") or item.get("title", "")).strip()
            if not source or source in seen_sources:
                continue
            seen_sources.add(source)
            top_sources.append(source)
            if len(top_sources) >= 3:
                break
        return {
            "total": len(references),
            "by_source_type": dict(source_counter),
            "by_kind": dict(kind_counter),
            "top_sources": top_sources,
        }

    def _sentences(self, value: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            return []
        parts = re.split(r"(?<=[。.!?;；])\s+|\n+", normalized)
        return [part.strip(" -") for part in parts if part.strip(" -")]

    def _looks_like_implementation_sentence(self, sentence: str) -> bool:
        lowered = sentence.lower()
        technical_hits = [
            "`" in sentence,
            "_" in sentence,
            "(" in sentence and ")" in sentence,
            any(
                token in lowered
                for token in (
                    "implement",
                    "implementation",
                    "call",
                    "pass",
                    "shows",
                    "show",
                    "uses",
                    "use",
                    "route",
                    "patch",
                    "cache",
                    "mask",
                    "token",
                    "forward",
                    "attention",
                    "api",
                    "kernel",
                    "repo",
                    "function",
                )
            ),
        ]
        return sum(1 for hit in technical_hits if hit) >= 2

    def _merge_strings(
        self,
        base: object,
        extra: list[str],
        *,
        limit: int,
    ) -> list[str]:
        return self._dedupe_strings([*self._coerce_strings(base), *extra], limit=limit)

    def _coerce_strings(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _dedupe_strings(self, values: list[str], *, limit: int) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = self._compact(value, max_chars=220)
            if not cleaned:
                continue
            signature = cleaned.lower()
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(cleaned)
            if len(deduped) >= limit:
                break
        return deduped

    def _dedupe_references(
        self,
        values: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in values:
            signature = (
                f"{str(item.get('source', '')).strip().lower()}::"
                f"{str(item.get('snippet', '')).strip().lower()[:180]}"
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _compact(self, value: object, *, max_chars: int) -> str:
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"
