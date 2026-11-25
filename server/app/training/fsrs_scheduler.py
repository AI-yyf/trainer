"""
FSRS-based Training Card Scheduler

Implements the FSRS algorithm for training card scheduling, replacing the custom scheduler.
This follows the strategy in docs/open-source-fit-and-provider-strategy.md which recommends
directly porting py-fsrs for the training engine.

Reference: https://github.com/open-spaced-repetition/py-fsrs (MIT License)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fsrs import Card, Rating, Scheduler, State

from ..core.clock import utc_now as _clock_now


class TrainingRating(Enum):
    """FSRS rating mapping for training cards
    
    Following Anki/FSRS conventions:
    - Again (1): Complete failure, show answer soon
    - Hard (2): Correct with significant difficulty
    - Good (3): Correct with some hesitation
    - Easy (4): Perfect recall, effortless
    """
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass
class TrainingCardState:
    """Training card state in FSRS terms"""
    card_id: str
    concept_id: str
    project_scope: str | None = None
    
    # FSRS fields
    stability: float = 0.0  # Retainability R in FSRS
    difficulty: float = 2.5  # Initial difficulty D
    state: str = "new"  # new, learning, review, relearning
    # py-fsrs learning step index. Persisting it is required for graduation
    # from minute-scale learning steps to a day-scale review interval.
    step: int = 0
    due: datetime | None = None
    interval: int = 0  # days
    ease_factor: float = 2.5  # Initial ease factor
    reps: int = 0
    lapses: int = 0
    
    # Trainer-specific fields
    card_type: str = "practice"  # practice, flash
    focus_area: str | None = None
    knowledge_type: str | None = None
    
    # Timestamps
    created_at: datetime = field(default_factory=_clock_now)
    last_reviewed_at: datetime | None = None
    next_due_at: datetime | None = None


@dataclass
class TrainingReviewResult:
    """Result of a training card review.

    ``retrievability`` is the FSRS recall probability immediately *before*
    this answer, not a capability score. Capability stays with evidence and
    skill projection; FSRS only owns memory timing.
    """
    card_id: str
    rating: TrainingRating
    new_stability: float
    new_difficulty: float
    new_interval: int
    next_due: datetime
    new_state: str
    step: int
    last_reviewed_at: datetime
    retrievability: float
    reps: int
    lapses: int
    elapsed_days: float


class FSRSTrainerCardScheduler:
    """
    FSRS-based scheduler for training cards.
    
    This replaces the custom ReviewScheduler in memory/review_scheduler.py
    with the scientifically-proven FSRS algorithm for optimal learning intervals.
    
    Key advantages:
    - Optimal review intervals based on forgetting curve
    - Adaptive difficulty based on performance
    - Reduced review time while maintaining retention
    - Quantifiable learning metrics (stability, difficulty, retrievability)
    """
    
    # FSRS parameters (can be tuned)
    DEFAULT_EASE_FACTOR = 2.5
    MIN_EASE_FACTOR = 1.3
    MAX_EASE_FACTOR = 4.0
    
    # Review ratings mapping
    RATING_MAP = {
        "again": TrainingRating.AGAIN,
        "hard": TrainingRating.HARD,
        "good": TrainingRating.GOOD,
        "easy": TrainingRating.EASY,
    }
    
    def __init__(self, deck_id: str = "trainer-default"):
        self.deck_id = deck_id
        self._scheduler = Scheduler()
        self._card_states: dict[str, TrainingCardState] = {}
        self._fsrs_rating_map = {
            TrainingRating.AGAIN: Rating.Again,
            TrainingRating.HARD: Rating.Hard,
            TrainingRating.GOOD: Rating.Good,
            TrainingRating.EASY: Rating.Easy,
        }
    
    def create_card(self, card_id: str, concept_id: str, **kwargs) -> TrainingCardState:
        """Create a new training card with initial FSRS state"""
        now = _clock_now()
        state = TrainingCardState(
            card_id=card_id,
            concept_id=concept_id,
            stability=0.0,
            difficulty=self.DEFAULT_EASE_FACTOR,
            state="new",
            due=now,
            next_due_at=now,
            **kwargs
        )
        self._card_states[card_id] = state
        return state
    
    def get_card_state(self, card_id: str) -> TrainingCardState | None:
        """Get the current state of a training card"""
        return self._card_states.get(card_id)
    
    def get_due_cards(self, limit: int = 20) -> list[TrainingCardState]:
        """Get cards that are due for review"""
        now = _clock_now()
        due_cards = []
        
        for card_state in self._card_states.values():
            if card_state.state == "new":
                # New cards are always due
                due_cards.append(card_state)
            elif card_state.due and card_state.due <= now:
                due_cards.append(card_state)
        
        # Sort by due date, then by stability (harder cards first)
        due_cards.sort(key=lambda c: (c.due or now, c.stability))
        return due_cards[:limit]
    
    def process_review(
        self,
        card_id: str,
        rating: TrainingRating | str,
    ) -> TrainingReviewResult:
        """
        Process a review response and update the card's FSRS state.

        FSRS owns the due date. A learner preference such as "review sooner"
        may change how the queue is surfaced, but it must not rewrite the
        retention model's interval after the fact.
        """
        # Normalize rating
        if isinstance(rating, str):
            rating = self.RATING_MAP.get(rating.lower(), TrainingRating.GOOD)

        card_state = self._card_states.get(card_id)
        if not card_state:
            raise ValueError(f"Card {card_id} not found")

        now = _clock_now()
        fsrs_card = self._create_fsrs_card(card_state)
        # The recall probability before this answer is retention evidence; the
        # post-review value is always ~1.0 and would tell the learner nothing.
        retrievability = self._scheduler.get_card_retrievability(fsrs_card, now)
        next_card, _ = self._scheduler.review_card(
            fsrs_card,
            self._fsrs_rating_map.get(rating, Rating.Good),
            now,
        )

        previous_reviewed_at = card_state.last_reviewed_at

        # Update card state with new values
        card_state.stability = next_card.stability if next_card.stability is not None else 0.0
        card_state.difficulty = (
            next_card.difficulty if next_card.difficulty is not None else self.DEFAULT_EASE_FACTOR
        )
        card_state.state = self._fsrs_state_name(next_card.state)
        card_state.step = max(0, int(next_card.step or 0))
        card_state.due = next_card.due
        card_state.next_due_at = next_card.due
        card_state.interval = (
            max(0, int(round((next_card.due - now).total_seconds() / 86400)))
            if next_card.due
            else 0
        )
        card_state.ease_factor = max(1.3, min(4.0, 5.0 - (card_state.difficulty or 0.0)))
        card_state.reps += 1
        if rating == TrainingRating.AGAIN:
            card_state.lapses += 1
        card_state.last_reviewed_at = now

        # Calculate elapsed days since the previous review, not the one we just wrote.
        elapsed_days = 0.0
        if previous_reviewed_at:
            elapsed_days = (now - previous_reviewed_at).total_seconds() / 86400

        return TrainingReviewResult(
            card_id=card_id,
            rating=rating,
            new_stability=card_state.stability,
            new_difficulty=card_state.difficulty,
            new_interval=card_state.interval,
            next_due=card_state.due or now,
            new_state=card_state.state,
            step=card_state.step,
            last_reviewed_at=now,
            retrievability=max(0.0, min(1.0, retrievability)),
            reps=card_state.reps,
            lapses=card_state.lapses,
            elapsed_days=elapsed_days,
        )

    def get_card_metrics(self, card_id: str) -> dict[str, Any]:
        """Get comprehensive metrics for a card."""
        card_state = self._card_states.get(card_id)
        if not card_state:
            return {}

        now = _clock_now()
        retrievability = self._scheduler.get_card_retrievability(
            self._create_fsrs_card(card_state),
            now,
        )

        return {
            "card_id": card_id,
            "concept_id": card_state.concept_id,
            "stability": round(card_state.stability, 2),
            "difficulty": round(card_state.difficulty, 2),
            "interval_days": card_state.interval,
            "ease_factor": round(card_state.ease_factor, 2),
            "retrievability": round(max(0.0, min(1.0, retrievability)), 3),
            "reps": card_state.reps,
            "lapses": card_state.lapses,
            "state": card_state.state,
            "due": card_state.due.isoformat() if card_state.due else None,
            "next_due": card_state.next_due_at.isoformat() if card_state.next_due_at else None,
        }
    
    def get_deck_statistics(self) -> dict[str, Any]:
        """Get overall deck statistics"""
        now = _clock_now()
        
        total = len(self._card_states)
        new_cards = sum(1 for c in self._card_states.values() if c.state == "new")
        learning = sum(1 for c in self._card_states.values() if c.state == "learning")
        review = sum(1 for c in self._card_states.values() if c.state == "review")
        
        due_now = sum(1 for c in self._card_states.values() 
                     if c.due and c.due <= now and c.state != "new")
        
        avg_stability = sum(c.stability for c in self._card_states.values()) / max(total, 1)
        retrievabilities = [
            self._scheduler.get_card_retrievability(self._create_fsrs_card(card), now)
            for card in self._card_states.values()
            if card.last_reviewed_at is not None and card.stability > 0
        ]
        avg_retrievability = (
            sum(retrievabilities) / len(retrievabilities) if retrievabilities else 0.0
        )

        return {
            "deck_id": self.deck_id,
            "total_cards": total,
            "new_cards": new_cards,
            "learning_cards": learning,
            "review_cards": review,
            "due_now": due_now,
            "average_stability": round(avg_stability, 2),
            "average_retrievability": round(avg_retrievability, 3),
        }
    
    def delete_card(self, card_id: str) -> bool:
        """Delete a card from the scheduler"""
        if card_id in self._card_states:
            del self._card_states[card_id]
            return True
        return False
    
    def load_card_states(self, states: list[TrainingCardState]) -> None:
        """Load multiple card states (e.g., from database)"""
        for state in states:
            self._card_states[state.card_id] = state
    
    def export_card_states(self) -> list[TrainingCardState]:
        """Export all card states (e.g., for database storage)"""
        return list(self._card_states.values())

    def _create_fsrs_card(self, card_state: TrainingCardState) -> Card:
        state = self._fsrs_state_from_name(card_state.state)
        stability = card_state.stability if card_state.stability > 0 else None
        difficulty = card_state.difficulty if card_state.difficulty > 0 else None
        return Card(
            state=state,
            step=max(0, int(card_state.step or 0)),
            stability=stability,
            difficulty=difficulty,
            due=card_state.due,
            last_review=card_state.last_reviewed_at,
        )

    def _fsrs_state_from_name(self, state: str) -> State:
        normalized = str(state or "").strip().lower()
        if normalized == "review":
            return State.Review
        if normalized == "relearning":
            return State.Relearning
        return State.Learning

    def _fsrs_state_name(self, state: State) -> str:
        return getattr(state, "name", str(state)).lower()


def create_training_scheduler(deck_id: str = "trainer-default") -> FSRSTrainerCardScheduler:
    """Factory function to create a new FSRS training scheduler"""
    return FSRSTrainerCardScheduler(deck_id=deck_id)


def card_state_to_payload(state: TrainingCardState) -> dict[str, Any]:
    """Serialize one FSRS card state for workspace persistence."""
    return {
        "card_id": state.card_id,
        "concept_id": state.concept_id,
        "project_scope": state.project_scope,
        "stability": state.stability,
        "difficulty": state.difficulty,
        "state": state.state,
        "step": max(0, int(state.step or 0)),
        "due": state.due.isoformat() if state.due else None,
        "interval": state.interval,
        "ease_factor": state.ease_factor,
        "reps": state.reps,
        "lapses": state.lapses,
        "card_type": state.card_type,
        "focus_area": state.focus_area,
        "knowledge_type": state.knowledge_type,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "last_reviewed_at": state.last_reviewed_at.isoformat() if state.last_reviewed_at else None,
        "next_due_at": state.next_due_at.isoformat() if state.next_due_at else None,
    }


def _parse_fsrs_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def card_state_from_payload(payload: dict[str, Any]) -> TrainingCardState | None:
    """Restore one FSRS card state from workspace payload. Fail-closed on bad ids."""
    card_id = str(payload.get("card_id") or payload.get("cardId") or "").strip()
    concept_id = str(payload.get("concept_id") or payload.get("conceptId") or "").strip()
    if not card_id:
        return None
    return TrainingCardState(
        card_id=card_id,
        concept_id=concept_id or card_id,
        project_scope=str(payload.get("project_scope") or payload.get("projectScope") or "").strip() or None,
        stability=float(payload.get("stability") or 0.0),
        difficulty=float(payload.get("difficulty") or 2.5),
        state=str(payload.get("state") or "new").strip() or "new",
        step=max(0, int(payload.get("step") or 0)),
        due=_parse_fsrs_datetime(payload.get("due")),
        interval=int(payload.get("interval") or 0),
        ease_factor=float(payload.get("ease_factor") or payload.get("easeFactor") or 2.5),
        reps=int(payload.get("reps") or 0),
        lapses=int(payload.get("lapses") or 0),
        card_type=str(payload.get("card_type") or payload.get("cardType") or "practice").strip() or "practice",
        focus_area=str(payload.get("focus_area") or payload.get("focusArea") or "").strip() or None,
        knowledge_type=str(payload.get("knowledge_type") or payload.get("knowledgeType") or "").strip() or None,
        created_at=_parse_fsrs_datetime(payload.get("created_at") or payload.get("createdAt"))
        or _clock_now(),
        last_reviewed_at=_parse_fsrs_datetime(
            payload.get("last_reviewed_at") or payload.get("lastReviewedAt")
        ),
        next_due_at=_parse_fsrs_datetime(payload.get("next_due_at") or payload.get("nextDueAt")),
    )
