"""Property-based tests for ResearchScheduler using Hypothesis."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.research.models import (
    Checkpoint,
    ResearchProject,
    ResearchTheme,
    ScheduleCadence,
    ScheduleSpec,
    ThemeStatus,
)
from app.research.scheduler import ResearchScheduler


# Custom strategies for generating test data
@st.composite
def valid_duration_weeks(draw):
    """Generate valid duration in weeks (1-52)."""
    return draw(st.integers(min_value=1, max_value=52))


@st.composite
def schedule_cadence(draw):
    """Generate a valid ScheduleCadence."""
    return draw(st.sampled_from([
        ScheduleCadence.DAILY,
        ScheduleCadence.WEEKLY,
        ScheduleCadence.BIWEEKLY,
        ScheduleCadence.MONTHLY,
    ]))


@st.composite
def theme_status(draw):
    """Generate a valid ThemeStatus."""
    return draw(st.sampled_from([
        ThemeStatus.PLANNING,
        ThemeStatus.ACTIVE,
        ThemeStatus.PAUSED,
        ThemeStatus.COMPLETED,
    ]))


@st.composite
def datetime_in_range(draw):
    """Generate a datetime within a reasonable range."""
    days_offset = draw(st.integers(min_value=-365, max_value=365))
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(days=days_offset)


@st.composite
def checkpoint(draw):
    """Generate a Checkpoint with random due date."""
    days_offset = draw(st.integers(min_value=-30, max_value=30))
    due_date = datetime.now(timezone.utc) + timedelta(days=days_offset)
    completed = draw(st.booleans())
    return Checkpoint(
        id=f"cp_{draw(st.integers(min_value=0, max_value=10000))}",
        label=f"Checkpoint {draw(st.integers(min_value=1, max_value=100))}",
        due_date=due_date,
        completed=completed,
    )


@st.composite
def checkpoints_list(draw):
    """Generate a list of checkpoints."""
    count = draw(st.integers(min_value=0, max_value=10))
    checkpoints = []
    for _i in range(count):
        cp = draw(checkpoint())
        checkpoints.append(cp)
    return checkpoints


@st.composite
def schedule_spec(draw):
    """Generate a ScheduleSpec with random parameters."""
    duration_weeks = draw(st.integers(min_value=1, max_value=12))
    cadence = draw(schedule_cadence())
    start_date = datetime.now(timezone.utc) - timedelta(weeks=draw(st.integers(min_value=0, max_value=4)))
    return ScheduleSpec.create(
        start_date=start_date,
        duration_weeks=duration_weeks,
        cadence=cadence,
    )


@st.composite
def research_theme(draw):
    """Generate a ResearchTheme with random parameters."""
    duration_weeks = draw(st.integers(min_value=1, max_value=12))
    cadence = draw(schedule_cadence())
    theme = ResearchTheme.create(
        title=f"Theme {draw(st.integers(min_value=1, max_value=100))}",
        description="Test theme",
        duration_weeks=duration_weeks,
        cadence=cadence,
    )
    # Optionally activate
    if draw(st.booleans()):
        theme.activate()
    return theme


@st.composite
def research_theme_with_progress(draw):
    """Generate a ResearchTheme with some checkpoints completed."""
    duration_weeks = draw(st.integers(min_value=1, max_value=12))
    cadence = draw(schedule_cadence())
    theme = ResearchTheme.create(
        title="Test Theme",
        description="Test",
        duration_weeks=duration_weeks,
        cadence=cadence,
    )
    # Complete some checkpoints
    if theme.schedule and theme.schedule.checkpoints:
        num_to_complete = draw(st.integers(min_value=0, max_value=len(theme.schedule.checkpoints)))
        for i in range(num_to_complete):
            theme.schedule.checkpoints[i].completed = True
    return theme


class TestResearchSchedulerProperties:
    """Property-based tests for ResearchScheduler."""

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoint_count_matches_duration(self, duration_weeks, cadence):
        """Property: More weeks -> more checkpoints (proportional to cadence)."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        # Calculate expected checkpoint count based on cadence
        if cadence == ScheduleCadence.DAILY:
            expected_max = duration_weeks * 7
        elif cadence == ScheduleCadence.WEEKLY:
            expected_max = duration_weeks
        elif cadence == ScheduleCadence.BIWEEKLY:
            expected_max = duration_weeks // 2 + (1 if duration_weeks % 2 else 0)
        else:  # MONTHLY
            expected_max = duration_weeks // 4 + (1 if duration_weeks % 4 else 0)
        
        # Checkpoint count should be reasonable
        assert len(schedule.checkpoints) >= 0
        assert len(schedule.checkpoints) <= expected_max + 1  # Allow for boundary conditions

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoint_dates_monotonic(self, duration_weeks, cadence):
        """Property: Checkpoint due dates should increase monotonically."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        for i in range(1, len(schedule.checkpoints)):
            assert schedule.checkpoints[i].due_date >= schedule.checkpoints[i - 1].due_date

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_progress_calculation(self, theme):
        """Property: Progress should be in [0.0, 100.0]."""
        progress = ResearchScheduler.progress_percentage(theme)
        assert 0.0 <= progress <= 100.0

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_progress_calculation_consistency(self, theme):
        """Property: Progress should match actual completed checkpoints."""
        if not theme.schedule or not theme.schedule.checkpoints:
            progress = ResearchScheduler.progress_percentage(theme)
            assert progress == 0.0
        else:
            completed = sum(1 for cp in theme.schedule.checkpoints if cp.completed)
            total = len(theme.schedule.checkpoints)
            expected_progress = (completed / total) * 100 if total > 0 else 0.0
            progress = ResearchScheduler.progress_percentage(theme)
            assert abs(progress - expected_progress) < 0.01

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_should_advance_only_for_active_themes(self, theme):
        """Property: should_advance should only return True for active themes."""
        result = ResearchScheduler.should_advance(theme)
        if theme.status != ThemeStatus.ACTIVE:
            assert result is False

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_schedule_status_has_required_fields(self, theme):
        """Property: schedule_status should return all required fields."""
        status = ResearchScheduler.schedule_status(theme)
        
        assert "theme_id" in status
        assert "theme_title" in status
        assert "status" in status
        assert "duration_weeks" in status
        assert "progress_percentage" in status
        assert "time_elapsed_percentage" in status
        assert "next_checkpoint" in status
        assert "overdue_checkpoints" in status
        assert "threads_count" in status
        assert "artifacts_count" in status

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_schedule_duration_matches_weeks(self, duration_weeks, cadence):
        """Property: Schedule duration should match specified weeks."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        expected_duration = timedelta(weeks=duration_weeks)
        
        # Allow for small floating point differences
        assert abs((schedule.duration - expected_duration).total_seconds()) < 1

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_time_elapsed_in_valid_range(self, theme):
        """Property: Time elapsed percentage should be in [0.0, 100.0]."""
        elapsed = ResearchScheduler.time_elapsed_percentage(theme)
        assert 0.0 <= elapsed <= 100.0

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_mark_checkpoint_complete_idempotent(self, theme):
        """Property: Marking same checkpoint complete twice should return False."""
        if not theme.schedule or not theme.schedule.checkpoints:
            return
        
        cp_id = theme.schedule.checkpoints[0].id
        # First mark
        result1 = ResearchScheduler.mark_checkpoint_complete(theme, cp_id)
        # Second mark (should return False since already completed)
        result2 = ResearchScheduler.mark_checkpoint_complete(theme, cp_id)
        
        assert result1 is True
        assert result2 is False

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_next_checkpoint_returns_valid_structure(self, theme):
        """Property: next_checkpoint should return valid structure if checkpoint exists."""
        theme.activate()
        next_cp = ResearchScheduler.next_checkpoint(theme)
        
        if next_cp is not None:
            assert "id" in next_cp
            assert "label" in next_cp
            assert "due_date" in next_cp
            assert "days_remaining" in next_cp

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_overdue_checkpoints_returns_list(self, theme):
        """Property: overdue_checkpoints should always return a list."""
        theme.activate()
        overdue = ResearchScheduler.overdue_checkpoints(theme)
        assert isinstance(overdue, list)

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoints_have_valid_ids(self, duration_weeks, cadence):
        """Property: All checkpoints should have valid IDs."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        for cp in schedule.checkpoints:
            assert cp.id.startswith("cp_")
            assert len(cp.id) > 3

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoints_have_labels(self, duration_weeks, cadence):
        """Property: All checkpoints should have non-empty labels."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        for cp in schedule.checkpoints:
            assert len(cp.label) > 0

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_progress_increases_with_completed_checkpoints(self, theme):
        """Property: More completed checkpoints -> higher progress."""
        if not theme.schedule or not theme.schedule.checkpoints:
            return
        
        completed_count = sum(1 for cp in theme.schedule.checkpoints if cp.completed)
        total = len(theme.schedule.checkpoints)
        progress = ResearchScheduler.progress_percentage(theme)
        
        # Progress should be proportional to completed count
        if total > 0:
            expected_min = (completed_count / total) * 100 - 0.01
            expected_max = (completed_count / total) * 100 + 0.01
            assert expected_min <= progress <= expected_max

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_theme_has_valid_id(self, theme):
        """Property: ResearchTheme should have a valid ID."""
        assert theme.id.startswith("theme_")
        assert len(theme.id) > 6

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_schedule_start_before_end(self, duration_weeks, cadence):
        """Property: Schedule start_date should be before end_date."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        assert schedule.start_date < schedule.end_date

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_threads_count_non_negative(self, theme):
        """Property: Threads count should always be non-negative."""
        status = ResearchScheduler.schedule_status(theme)
        assert status["threads_count"] >= 0

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_artifacts_count_non_negative(self, theme):
        """Property: Artifacts count should always be non-negative."""
        status = ResearchScheduler.schedule_status(theme)
        assert status["artifacts_count"] >= 0


class TestResearchProjectProperties:
    """Property-based tests for ResearchProject."""

    @given(
        title=st.text(min_size=1, max_size=50),
        description=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=50)
    def test_project_has_valid_id(self, title, description):
        """Property: ResearchProject should have a valid ID."""
        project = ResearchProject.create(title=title, description=description)
        assert project.id.startswith("proj_")
        assert len(project.id) > 5

    @given(
        title=st.text(min_size=1, max_size=50),
        description=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=50)
    def test_project_has_initial_message(self, title, description):
        """Property: New project should have initial gate message."""
        project = ResearchProject.create(title=title, description=description)
        assert len(project.gate.messages) >= 1

    @given(
        title=st.text(min_size=1, max_size=50),
        description=st.text(min_size=1, max_size=200),
        num_themes=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=30)
    def test_project_themes_count(self, title, description, num_themes):
        """Property: Project themes count should match added themes."""
        project = ResearchProject.create(title=title, description=description)
        for i in range(num_themes):
            project.add_theme(
                title=f"Theme {i}",
                description=f"Description {i}",
                duration_weeks=2,
            )
        assert len(project.themes) == num_themes


if __name__ == "__main__":
    import unittest
    unittest.main()
