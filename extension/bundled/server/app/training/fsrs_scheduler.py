"""
FSRS-based Training Card Scheduler

Implements the FSRS algorithm for training card scheduling, replacing the custom scheduler.
This follows the strategy in docs/open-source-fit-and-provider-strategy.md which recommends
directly porting py-fsrs for the training engine.

Reference: https://github.com/open-spaced-repetition/py-fsrs (MIT License)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from fsrs import Card, Rating, Scheduler, State

from ..pedagogy.evidence_controls import apply_review_frequency_bias


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
    due: datetime | None = None
    interval: int = 0  # days
    ease_factor: float = 2.5  # Initial ease factor
    reps: int = 0
    lapses: int = 0
    
    # Trainer-specific fields
    card_type: str = "practice"  # practice, flash
    focus_area: str | None = None
    knowledge_type: str | None = None
    mastery_score: float = 0.0
    
    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_reviewed_at: datetime | None = None
    next_due_at: datetime | None = None


@dataclass
class TrainingReviewResult:
    """Result of a training card review"""
    card_id: str
    rating: TrainingRating
    new_stability: float
    new_difficulty: float
    new_interval: int
    next_due: datetime
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        *,
        review_frequency: str = "normal",
    ) -> TrainingReviewResult:
        """
        Process a review response and update the card's FSRS state.
        
        This implements the FSRS scheduling algorithm to calculate
        optimal next review intervals.
        """
        # Normalize rating
        if isinstance(rating, str):
            rating = self.RATING_MAP.get(rating.lower(), TrainingRating.GOOD)
        
        card_state = self._card_states.get(card_id)
        if not card_state:
            raise ValueError(f"Card {card_id} not found")
        
        now = datetime.now(timezone.utc)
        fsrs_card = self._create_fsrs_card(card_state)
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
        card_state.due = next_card.due
        card_state.next_due_at = next_card.due
        raw_interval = max(0, int(round((next_card.due - now).total_seconds() / 86400))) if next_card.due else 0
        card_state.interval = apply_review_frequency_bias(raw_interval, review_frequency)
        if next_card.due and card_state.interval != raw_interval:
            card_state.due = now + timedelta(days=card_state.interval)
            card_state.next_due_at = card_state.due
        card_state.ease_factor = max(1.3, min(4.0, 5.0 - (card_state.difficulty or 0.0)))
        card_state.reps += 1
        if rating == TrainingRating.AGAIN:
            card_state.lapses += 1
        card_state.last_reviewed_at = now

        # Calculate elapsed days since the previous review, not the one we just wrote.
        elapsed_days = 0.0
        if previous_reviewed_at:
            elapsed_days = (now - previous_reviewed_at).total_seconds() / 86400
        
        # Calculate mastery score based on stability
        card_state.mastery_score = self._calculate_mastery(card_state)
        
        return TrainingReviewResult(
            card_id=card_id,
            rating=rating,
            new_stability=card_state.stability,
            new_difficulty=card_state.difficulty,
            new_interval=card_state.interval,
            next_due=card_state.due or now,
            reps=card_state.reps,
            lapses=card_state.lapses,
            elapsed_days=elapsed_days,
        )
    
    def _calculate_mastery(self, card_state: TrainingCardState) -> float:
        """
        Calculate mastery score based on card stability and ease.
        
        Returns a value between 0.0 and 1.0:
        - 0.0-0.3: Beginning learner
        - 0.3-0.6: Developing skill
        - 0.6-0.8: Competent performer
        - 0.8-1.0: Expert/master
        """
        # Stability factor: higher stability = better retention
        stability_factor = min(card_state.stability / 30.0, 1.0)
        
        # Ease factor: higher ease = easier to recall
        ease_factor = (card_state.ease_factor - self.MIN_EASE_FACTOR) / (self.MAX_EASE_FACTOR - self.MIN_EASE_FACTOR)
        ease_factor = max(0.0, min(1.0, ease_factor))
        
        # Review count bonus (more reviews = more practiced)
        reps_factor = min(card_state.reps / 20.0, 1.0)
        
        # Lapse penalty (lapses indicate difficulty)
        lapse_penalty = min(card_state.lapses * 0.1, 0.3)
        
        # Combined mastery score
        mastery = (stability_factor * 0.4 + ease_factor * 0.3 + reps_factor * 0.3) - lapse_penalty
        return max(0.0, min(1.0, mastery))
    
    def get_card_metrics(self, card_id: str) -> dict[str, Any]:
        """Get comprehensive metrics for a card"""
        card_state = self._card_states.get(card_id)
        if not card_state:
            return {}
        
        # Calculate retrievability (probability of recall)
        now = datetime.now(timezone.utc)
        if card_state.last_reviewed_at:
            elapsed = (now - card_state.last_reviewed_at).total_seconds() / 86400
            retrievability = self._calculate_retrievability(card_state.stability, elapsed)
        else:
            retrievability = 0.0
        
        return {
            "card_id": card_id,
            "concept_id": card_state.concept_id,
            "stability": round(card_state.stability, 2),
            "difficulty": round(card_state.difficulty, 2),
            "interval_days": card_state.interval,
            "ease_factor": round(card_state.ease_factor, 2),
            "mastery_score": round(card_state.mastery_score, 3),
            "retrievability": round(retrievability, 3),
            "reps": card_state.reps,
            "lapses": card_state.lapses,
            "state": card_state.state,
            "due": card_state.due.isoformat() if card_state.due else None,
            "next_due": card_state.next_due_at.isoformat() if card_state.next_due_at else None,
        }
    
    def _calculate_retrievability(self, stability: float, elapsed_days: float) -> float:
        """
        Calculate retrievability using the FSRS forgetting curve.
        
        R = e^(-t/S) where S is stability and t is elapsed time
        """
        import math
        if stability <= 0:
            return 0.0
        retrievability = math.exp(-elapsed_days / stability)
        return max(0.0, min(1.0, retrievability))
    
    def get_deck_statistics(self) -> dict[str, Any]:
        """Get overall deck statistics"""
        now = datetime.now(timezone.utc)
        
        total = len(self._card_states)
        new_cards = sum(1 for c in self._card_states.values() if c.state == "new")
        learning = sum(1 for c in self._card_states.values() if c.state == "learning")
        review = sum(1 for c in self._card_states.values() if c.state == "review")
        
        due_now = sum(1 for c in self._card_states.values() 
                     if c.due and c.due <= now and c.state != "new")
        
        avg_stability = sum(c.stability for c in self._card_states.values()) / max(total, 1)
        avg_mastery = sum(c.mastery_score for c in self._card_states.values()) / max(total, 1)
        
        return {
            "deck_id": self.deck_id,
            "total_cards": total,
            "new_cards": new_cards,
            "learning_cards": learning,
            "review_cards": review,
            "due_now": due_now,
            "average_stability": round(avg_stability, 2),
            "average_mastery": round(avg_mastery, 3),
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
        "due": state.due.isoformat() if state.due else None,
        "interval": state.interval,
        "ease_factor": state.ease_factor,
        "reps": state.reps,
        "lapses": state.lapses,
        "card_type": state.card_type,
        "focus_area": state.focus_area,
        "knowledge_type": state.knowledge_type,
        "mastery_score": state.mastery_score,
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
        due=_parse_fsrs_datetime(payload.get("due")),
        interval=int(payload.get("interval") or 0),
        ease_factor=float(payload.get("ease_factor") or payload.get("easeFactor") or 2.5),
        reps=int(payload.get("reps") or 0),
        lapses=int(payload.get("lapses") or 0),
        card_type=str(payload.get("card_type") or payload.get("cardType") or "practice").strip() or "practice",
        focus_area=str(payload.get("focus_area") or payload.get("focusArea") or "").strip() or None,
        knowledge_type=str(payload.get("knowledge_type") or payload.get("knowledgeType") or "").strip() or None,
        mastery_score=float(payload.get("mastery_score") or payload.get("masteryScore") or 0.0),
        created_at=_parse_fsrs_datetime(payload.get("created_at") or payload.get("createdAt"))
        or datetime.now(timezone.utc),
        last_reviewed_at=_parse_fsrs_datetime(
            payload.get("last_reviewed_at") or payload.get("lastReviewedAt")
        ),
        next_due_at=_parse_fsrs_datetime(payload.get("next_due_at") or payload.get("nextDueAt")),
    )
