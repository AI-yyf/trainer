from __future__ import annotations

import json
import uuid

from app.core.models import (
    ChatMessage,
    LearningPlan,
    PlanUpdateRequest,
    SessionRecord,
    UserProfile,
    WorkspaceContext,
    utc_now_iso,
)
from app.db.database import Database


class SessionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_session(
        self,
        *,
        user_profile: UserProfile,
        workspace_context: WorkspaceContext,
        stage: str,
        summary: str,
    ) -> SessionRecord:
        session_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, stage, summary, user_profile_json,
                    workspace_context_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    stage,
                    summary,
                    user_profile.model_dump_json(),
                    workspace_context.model_dump_json(),
                    now,
                    now,
                ),
            )
        return SessionRecord(
            session_id=session_id,
            stage=stage,
            summary=summary,
            user_profile=user_profile,
            workspace_context=workspace_context,
            created_at=now,
            updated_at=now,
        )

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionRecord(
            session_id=row["session_id"],
            stage=row["stage"],
            summary=row["summary"],
            user_profile=UserProfile.model_validate_json(row["user_profile_json"]),
            workspace_context=WorkspaceContext.model_validate_json(
                row["workspace_context_json"]
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def add_message(self, session_id: str, message: ChatMessage) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO session_messages (session_id, role, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message.role,
                    message.content,
                    json.dumps(message.metadata),
                    message.created_at,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (utc_now_iso(), session_id),
            )

    def list_messages(self, session_id: str, *, limit: int = 50) -> list[ChatMessage]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT role, content, metadata_json, created_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY message_id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        messages = [
            ChatMessage(
                role=row["role"],
                content=row["content"],
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
        messages.reverse()
        return messages

    def update_summary(self, session_id: str, summary: str) -> None:
        with self.database.connection() as conn:
            conn.execute(
                "UPDATE sessions SET summary = ?, updated_at = ? WHERE session_id = ?",
                (summary, utc_now_iso(), session_id),
            )


class PlanRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_plan(self, plan: LearningPlan) -> LearningPlan:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO learning_plan (
                    plan_id, session_id, title, objective, frozen,
                    weekly_cadence, default_answer_policy, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.session_id,
                    plan.title,
                    plan.objective,
                    int(plan.frozen),
                    plan.weekly_cadence,
                    plan.default_answer_policy,
                    plan.model_dump_json(),
                    plan.created_at,
                    plan.updated_at,
                ),
            )
        return plan

    def get_plan(self, plan_id: str) -> LearningPlan | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM learning_plan WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return LearningPlan.model_validate_json(row["payload_json"])

    def update_plan(self, request: PlanUpdateRequest) -> LearningPlan | None:
        existing = self.get_plan(request.plan_id)
        if existing is None:
            return None
        update_payload = request.model_dump(exclude_none=True)
        update_payload.pop("plan_id", None)
        merged = existing.model_copy(update=update_payload)
        merged.updated_at = utc_now_iso()
        with self.database.connection() as conn:
            conn.execute(
                """
                UPDATE learning_plan
                SET title = ?, objective = ?, frozen = ?, weekly_cadence = ?,
                    default_answer_policy = ?, payload_json = ?, updated_at = ?
                WHERE plan_id = ?
                """,
                (
                    merged.title,
                    merged.objective,
                    int(merged.frozen),
                    merged.weekly_cadence,
                    merged.default_answer_policy,
                    merged.model_dump_json(),
                    merged.updated_at,
                    merged.plan_id,
                ),
            )
        return merged

    def latest_for_session(self, session_id: str) -> LearningPlan | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM learning_plan
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return LearningPlan.model_validate_json(row["payload_json"])
