"""LearnerState is one workspace-scoped read projection, not a new store."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.models import (
    GoalSession,
    MemorySnapshot,
    ReviewQueueItem,
    UserProfile,
)
from app.learner_state import LearnerStateService, collect_unified_evidence, learner_profile


class _Repository:
    def __init__(self, profiles: dict[str, UserProfile | None] | None = None) -> None:
        self.profiles = profiles or {}

    def get_profile(self, workspace_id: str) -> UserProfile | None:
        return self.profiles.get(workspace_id)


class _Goals:
    def __init__(self, goals: dict[str, GoalSession | None] | None = None) -> None:
        self.goals = goals or {}

    def current(self, workspace_id: str) -> GoalSession | None:
        return self.goals.get(workspace_id)


class _Memory:
    def __init__(self, snapshots: dict[str, MemorySnapshot] | None = None) -> None:
        self.snapshots = snapshots or {}

    def snapshot(self, workspace_id: str) -> MemorySnapshot:
        return self.snapshots.get(workspace_id, MemorySnapshot())

    def latest_handoff_evidence(self, workspace_id: str):
        return (None, [])

    def evidence_queue(self, workspace_id: str):
        return SimpleNamespace(pending=[], deferred=[], adopted=[], rejected=[], history=[])


class _Attempts:
    def __init__(self, evidence: dict[str, list[dict]] | None = None) -> None:
        self.evidence = evidence or {}

    def list_workspace_evidence(self, workspace_id: str, *, limit: int = 50) -> list[dict]:
        return list(self.evidence.get(workspace_id, []))[:limit]


def _goal(workspace_id: str) -> GoalSession:
    return GoalSession(
        goalId=f"goal-{workspace_id}",
        workspaceId=workspace_id,
        title="Build reliable distributed systems",
    )


def _evidence(workspace_id: str) -> list[dict]:
    return [
        {
            "evidence_id": f"ev-{workspace_id}",
            "attempt_id": f"attempt-{workspace_id}",
            "workspace_id": workspace_id,
            "card_id": f"card-{workspace_id}",
            "result": "passed",
            "trust_level": "controlled_check",
            "assistance_level": "independent",
            "created_at": "2026-11-09T01:00:00+00:00",
            "artifact_hash": f"hash-{workspace_id}",
        }
    ]


def _service(
    *,
    profiles: dict[str, UserProfile | None],
    snapshots: dict[str, MemorySnapshot],
    goals: dict[str, GoalSession | None],
    evidence: dict[str, list[dict]],
) -> LearnerStateService:
    return LearnerStateService(
        _Repository(profiles),  # type: ignore[arg-type]
        _Memory(snapshots),  # type: ignore[arg-type]
        _Goals(goals),  # type: ignore[arg-type]
        _Attempts(evidence),  # type: ignore[arg-type]
    )


def test_projection_exposes_profile_goal_memory_mastery_evidence_and_review() -> None:
    memory_a = MemorySnapshot(
        current_focus="PPO clipping",
        top_weakness="policy-gradient derivation",
        recent_wins=["implemented a ratio calculation"],
        due_review_count=2,
        due_reviews=[
            ReviewQueueItem(
                concept="PPO clipping",
                reason="two days since the last recall",
                due_at="2026-11-09T09:00:00+00:00",
                evidence_basis="fsrs_recall",
            )
        ],
        workspace={
            "training_skill_projection": {
                "dimensions": {"implementation": {"state": "independent"}}
            }
        },
    )
    service = _service(
        profiles={"ws-a": UserProfile(long_term_goal="Learn PPO")},
        snapshots={"ws-a": memory_a},
        goals={"ws-a": _goal("ws-a")},
        evidence={"ws-a": _evidence("ws-a")},
    )

    projection = service.snapshot("ws-a")
    payload = projection.to_payload()

    assert payload["workspace_id"] == "ws-a"
    assert payload["profile"]["confidence"] == "known"
    assert payload["profile"]["value"]["long_term_goal"] == "Learn PPO"
    assert payload["goal"]["confidence"] == "known"
    assert payload["goal"]["value"]["goalId"] == "goal-ws-a"
    assert payload["memory"]["current_focus"] == "PPO clipping"
    assert payload["mastery"]["confidence"] == "known"
    assert payload["mastery"]["dimensions"]["implementation"]["state"] == "independent"
    assert payload["evidence"]["total"] == 1
    assert payload["evidence"]["items"][0]["workspace_id"] == "ws-a"
    assert payload["review"]["due_count"] == 2
    assert payload["review"]["due_items"][0]["concept"] == "PPO clipping"
    assert set(payload["ownership"]) == {
        "profile",
        "goal",
        "memory",
        "mastery",
        "evidence",
        "review",
    }


def test_projection_is_workspace_scoped_and_never_leaks_another_project() -> None:
    service = _service(
        profiles={
            "ws-a": UserProfile(long_term_goal="Learn PPO"),
            "ws-b": UserProfile(long_term_goal="Learn Kubernetes"),
        },
        snapshots={
            "ws-a": MemorySnapshot(current_focus="PPO", due_review_count=1),
            "ws-b": MemorySnapshot(current_focus="Kubernetes", due_review_count=0),
        },
        goals={"ws-a": _goal("ws-a"), "ws-b": _goal("ws-b")},
        evidence={"ws-a": _evidence("ws-a"), "ws-b": _evidence("ws-b")},
    )

    a = service.snapshot("ws-a").to_payload()
    b = service.snapshot("ws-b").to_payload()

    assert a["profile"]["value"]["long_term_goal"] == "Learn PPO"
    assert b["profile"]["value"]["long_term_goal"] == "Learn Kubernetes"
    assert a["goal"]["value"]["goalId"] == "goal-ws-a"
    assert b["goal"]["value"]["goalId"] == "goal-ws-b"
    assert a["memory"]["current_focus"] == "PPO"
    assert b["memory"]["current_focus"] == "Kubernetes"
    assert [item["workspace_id"] for item in a["evidence"]["items"]] == ["ws-a"]
    assert [item["workspace_id"] for item in b["evidence"]["items"]] == ["ws-b"]
    assert "Kubernetes" not in str(a)


def test_missing_facts_are_unknown_or_insufficient_not_fabricated() -> None:
    service = _service(profiles={}, snapshots={}, goals={}, evidence={})
    payload = service.snapshot("ws-empty").to_payload()

    assert payload["profile"]["confidence"] == "unknown"
    assert payload["profile"]["value"] is None
    assert payload["goal"]["confidence"] == "unknown"
    assert payload["goal"]["value"] is None
    assert payload["mastery"]["confidence"] == "insufficient_evidence"
    assert payload["mastery"]["dimensions"] == {}
    assert payload["evidence"]["confidence"] == "insufficient_evidence"
    assert payload["evidence"]["items"] == []
    assert payload["review"]["due_count"] == 0
    assert payload["review"]["confidence"] == "known"


def test_preference_correction_is_read_immediately_without_a_parallel_cache() -> None:
    profiles: dict[str, UserProfile | None] = {
        "ws-a": UserProfile(long_term_goal="Learn PPO", teaching_style="hands-on")
    }
    service = _service(profiles=profiles, snapshots={}, goals={}, evidence={})

    before = service.snapshot("ws-a").to_payload()
    assert before["profile"]["value"]["teaching_style"] == "hands-on"

    profiles["ws-a"] = UserProfile(long_term_goal="Learn PPO", teaching_style="concept-first")
    after = service.snapshot("ws-a").to_payload()

    assert after["profile"]["value"]["teaching_style"] == "concept-first"
    assert after["generated_at"] >= before["generated_at"]


def test_evidence_collection_is_the_same_workspace_scoped_list() -> None:
    attempts = _Attempts({"ws-a": _evidence("ws-a")})
    items = collect_unified_evidence(
        memory_service=None,
        attempt_store=attempts,  # type: ignore[arg-type]
        workspace_id="ws-a",
    )
    assert len(items) == 1
    assert items[0].workspace_id == "ws-a"
    assert items[0].evidence_id == "ev-ws-a"


def test_learner_profile_reads_through_the_projection_not_a_parallel_cache() -> None:
    service = _service(
        profiles={"ws-a": UserProfile(long_term_goal="Learn PPO")},
        snapshots={},
        goals={},
        evidence={},
    )
    runtime = SimpleNamespace(
        learner_state_service=service,
        repository=SimpleNamespace(
            get_profile=lambda workspace_id: UserProfile(long_term_goal="stale fallback")
        ),
    )

    profile = learner_profile(runtime, "ws-a")

    assert profile is not None
    assert profile.long_term_goal == "Learn PPO"


def test_learner_profile_falls_back_without_the_projection_service() -> None:
    runtime = SimpleNamespace(repository=_Repository({"ws-a": UserProfile(long_term_goal="Kubernetes")}))

    profile = learner_profile(runtime, "ws-a")

    assert profile is not None
    assert profile.long_term_goal == "Kubernetes"


def test_learner_state_endpoint_returns_the_same_workspace_scoped_projection(tmp_path) -> None:
    from tests.test_api import build_client

    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": "ws-endpoint", "workspace_name": "Endpoint workspace"},
        )
        assert started.status_code == 200, started.text

        response = client.get("/learner/state", params={"workspace_id": "ws-endpoint"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["workspace_id"] == "ws-endpoint"
        assert set(payload["ownership"]) == {
            "profile",
            "goal",
            "memory",
            "mastery",
            "evidence",
            "review",
        }
        assert payload["profile"]["confidence"] in {"known", "unknown"}
        assert payload["mastery"]["confidence"] in {"known", "insufficient_evidence"}
        assert payload["evidence"]["confidence"] in {"known", "insufficient_evidence"}

        other = client.get("/learner/state", params={"workspace_id": "ws-other"})
        assert other.status_code == 200, other.text
        assert other.json()["workspace_id"] == "ws-other"
        assert other.json()["profile"]["value"] is None
