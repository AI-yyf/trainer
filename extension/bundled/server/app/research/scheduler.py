from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import ThemeStatus

if TYPE_CHECKING:
    from .models import ResearchProject, ResearchTheme


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchScheduler:
    @staticmethod
    def should_advance(theme: ResearchTheme) -> bool:
        if theme.status != ThemeStatus.ACTIVE or not theme.schedule:
            return False
        now = utc_now()
        for cp in theme.schedule.checkpoints:
            if not cp.completed and now >= cp.due_date:
                return True
        return False

    @staticmethod
    def next_checkpoint(theme: ResearchTheme) -> dict | None:
        if not theme.schedule:
            return None
        now = utc_now()
        for cp in theme.schedule.checkpoints:
            if not cp.completed and cp.due_date > now:
                return {
                    "id": cp.id,
                    "label": cp.label,
                    "due_date": cp.due_date.isoformat(),
                    "days_remaining": (cp.due_date - now).days,
                }
        return None

    @staticmethod
    def overdue_checkpoints(theme: ResearchTheme) -> list[dict]:
        if not theme.schedule:
            return []
        now = utc_now()
        return [
            {"id": cp.id, "label": cp.label, "due_date": cp.due_date.isoformat(), "days_overdue": (now - cp.due_date).days}
            for cp in theme.schedule.checkpoints
            if not cp.completed and now >= cp.due_date
        ]

    @staticmethod
    def mark_checkpoint_complete(theme: ResearchTheme, checkpoint_id: str) -> bool:
        if not theme.schedule:
            return False
        for cp in theme.schedule.checkpoints:
            if cp.id == checkpoint_id and not cp.completed:
                cp.completed = True
                cp.completed_at = utc_now()
                theme.updated_at = utc_now()
                return True
        return False

    @staticmethod
    def progress_percentage(theme: ResearchTheme) -> float:
        if not theme.schedule or not theme.schedule.checkpoints:
            return 0.0
        completed = sum(1 for cp in theme.schedule.checkpoints if cp.completed)
        return completed / len(theme.schedule.checkpoints) * 100

    @staticmethod
    def time_elapsed_percentage(theme: ResearchTheme) -> float:
        if not theme.schedule:
            return 0.0
        now = utc_now()
        if now < theme.schedule.start_date:
            return 0.0
        if now > theme.schedule.end_date:
            return 100.0
        elapsed = now - theme.schedule.start_date
        return elapsed.total_seconds() / theme.schedule.duration.total_seconds() * 100

    @staticmethod
    def themes_needing_advance(project: ResearchProject) -> list[ResearchTheme]:
        return [t for t in project.themes if ResearchScheduler.should_advance(t)]

    @staticmethod
    def schedule_status(theme: ResearchTheme) -> dict:
        return {
            "theme_id": theme.id,
            "theme_title": theme.title,
            "status": theme.status,
            "duration_weeks": theme.duration_weeks,
            "progress_percentage": ResearchScheduler.progress_percentage(theme),
            "time_elapsed_percentage": ResearchScheduler.time_elapsed_percentage(theme),
            "next_checkpoint": ResearchScheduler.next_checkpoint(theme),
            "overdue_checkpoints": ResearchScheduler.overdue_checkpoints(theme),
            "threads_count": len(theme.threads),
            "artifacts_count": len(theme.artifacts),
        }

    @staticmethod
    def project_schedule_status(project: ResearchProject) -> dict:
        return {
            "project_id": project.id,
            "project_title": project.title,
            "themes": [ResearchScheduler.schedule_status(t) for t in project.themes],
            "themes_needing_advance": [t.id for t in ResearchScheduler.themes_needing_advance(project)],
            "total_checkpoints": sum(len(t.schedule.checkpoints) if t.schedule else 0 for t in project.themes),
            "completed_checkpoints": sum(
                sum(1 for cp in t.schedule.checkpoints if cp.completed) if t.schedule else 0 for t in project.themes
            ),
        }
