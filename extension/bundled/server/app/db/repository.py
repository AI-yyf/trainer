from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.models import (
    AssetLink,
    AssetRevision,
    GlobalMemory,
    GlobalPlan,
    GlobalPlanProjectLink,
    LearningPlan,
    LibraryAsset,
    LocalOwner,
    MemoryShareGrant,
    ProjectContext,
    ProjectProvisioning,
    ResourceRecord,
    SubPlan,
    TeachingKnowledgeAsset,
    TrainerProject,
    TrainerRoot,
    UserProfile,
    utc_now_iso,
)

DEFAULT_LOCAL_OWNER_ID = "local-trainer"
DEFAULT_LOCAL_OWNER_NAME = "Local Trainer"
WINDOWS_WORKSPACE_ALIAS_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


class TrainerRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_profile (
                    workspace_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_plan (
                    plan_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subplans (
                    subplan_id TEXT PRIMARY KEY,
                    parent_plan_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_subplans_parent_plan
                ON subplans(parent_plan_id);
                CREATE TABLE IF NOT EXISTS concept_mastery (
                    workspace_id TEXT NOT NULL,
                    concept TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (workspace_id, concept)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mistakes (
                    mistake_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reflections (
                    reflection_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resources (
                    resource_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resource_tombstones (
                    workspace_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    deletion_payload TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, resource_id)
                );
                CREATE INDEX IF NOT EXISTS idx_resource_tombstones_workspace_deleted_at
                ON resource_tombstones(workspace_id, deleted_at DESC);
                CREATE TABLE IF NOT EXISTS teaching_assets (
                    asset_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_turn_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    context_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_turn_checkpoints_workspace_session
                ON agent_turn_checkpoints(workspace_id, session_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS structured_memory (
                    workspace_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_provisionings (
                    workspace_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_project_provisionings_project
                ON project_provisionings(project_id);
                CREATE TABLE IF NOT EXISTS identity_schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trainer_roots (
                    root_id TEXT PRIMARY KEY,
                    root_path TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trainer_projects (
                    project_id TEXT PRIMARY KEY,
                    root_id TEXT NOT NULL,
                    project_path TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(root_id, project_path)
                );
                CREATE INDEX IF NOT EXISTS idx_trainer_projects_root
                ON trainer_projects(root_id);
                CREATE TABLE IF NOT EXISTS project_contexts (
                    context_id TEXT PRIMARY KEY,
                    root_id TEXT NOT NULL,
                    project_id TEXT NOT NULL UNIQUE,
                    legacy_workspace_id TEXT UNIQUE,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_project_contexts_root
                ON project_contexts(root_id);
                CREATE TABLE IF NOT EXISTS workspace_context_aliases (
                    alias TEXT PRIMARY KEY,
                    context_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workspace_context_aliases_context
                ON workspace_context_aliases(context_id);
                CREATE TABLE IF NOT EXISTS memory_share_grants (
                    source_workspace_id TEXT NOT NULL,
                    target_workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (source_workspace_id, target_workspace_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_share_grants_target
                ON memory_share_grants(target_workspace_id);
                CREATE TABLE IF NOT EXISTS local_owners (
                    owner_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS global_memory (
                    owner_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transfer_promotion_exclusions (
                    workspace_id TEXT PRIMARY KEY,
                    excluded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transfer_promotion_exclusion_history (
                    workspace_id TEXT PRIMARY KEY,
                    excluded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS global_plans (
                    global_plan_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS global_plan_project_links (
                    global_plan_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    project_plan_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (global_plan_id, workspace_id)
                );
                CREATE INDEX IF NOT EXISTS idx_global_plan_project_links_project
                ON global_plan_project_links(project_plan_id);
                CREATE TABLE IF NOT EXISTS library_assets (
                    asset_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    project_id TEXT,
                    context_id TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    deleted_at TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_library_assets_owner
                ON library_assets(owner_id);
                CREATE TABLE IF NOT EXISTS asset_revisions (
                    revision_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    parent_revision_id TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_asset_revisions_owner_asset
                ON asset_revisions(owner_id, asset_id);
                CREATE TABLE IF NOT EXISTS asset_links (
                    link_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    source_ref TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL,
                    UNIQUE(owner_id, asset_id, workspace_id, relation, source_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_asset_links_owner_workspace
                ON asset_links(owner_id, workspace_id);
                CREATE TABLE IF NOT EXISTS plan_change_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plan_change_candidates_workspace_status
                ON plan_change_candidates(workspace_id, status, created_at DESC);
                """
            )
            self._migrate_library_asset_schema(connection)
            self._migrate_legacy_workspace_identity(connection)

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        existing = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _migrate_library_asset_schema(self, connection: sqlite3.Connection) -> None:
        self._ensure_column(connection, "library_assets", "project_id", "TEXT")
        self._ensure_column(connection, "library_assets", "context_id", "TEXT")
        self._ensure_column(connection, "library_assets", "status", "TEXT NOT NULL DEFAULT 'active'")
        self._ensure_column(connection, "library_assets", "deleted_at", "TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_library_assets_owner_status ON library_assets(owner_id, status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_library_assets_owner_project ON library_assets(owner_id, project_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_library_assets_owner_context ON library_assets(owner_id, context_id)"
        )

    def save_profile(self, workspace_id: str, profile: UserProfile) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_profile (workspace_id, payload)
                VALUES (?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET payload = excluded.payload
                """,
                (workspace_id, profile.model_dump_json()),
            )

    def get_profile(self, workspace_id: str) -> UserProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM user_profile WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        return UserProfile.model_validate_json(row["payload"]) if row else None

    def save_plan(self, workspace_id: str, plan: LearningPlan) -> None:
        scope = (workspace_id or "").strip()
        existing = (getattr(plan, "workspace_id", None) or "").strip()
        if scope and not (existing and existing != scope):
            plan.workspace_id = existing or scope
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO learning_plan (plan_id, workspace_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET payload = excluded.payload
                """,
                (plan.id, workspace_id, plan.model_dump_json()),
            )

    def get_latest_plan(self, workspace_id: str) -> LearningPlan | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM learning_plan
                WHERE workspace_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        return LearningPlan.model_validate_json(row["payload"]) if row else None

    def list_plans(self, workspace_id: str) -> list[LearningPlan]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM learning_plan
                WHERE workspace_id = ?
                ORDER BY rowid ASC
                """,
                (workspace_id,),
            ).fetchall()
        return [LearningPlan.model_validate_json(row["payload"]) for row in rows]

    def save_plan_change_candidate(self, candidate) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO plan_change_candidates
                    (candidate_id, workspace_id, plan_id, status, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    status = excluded.status, payload = excluded.payload
                """,
                (
                    candidate.id,
                    candidate.workspace_id,
                    candidate.plan_id,
                    candidate.status,
                    candidate.created_at,
                    candidate.model_dump_json(),
                ),
            )

    def get_plan_change_candidate(self, candidate_id: str):
        from ..core.models import PlanChangeCandidate

        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM plan_change_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return PlanChangeCandidate.model_validate_json(row["payload"]) if row else None

    def list_plan_change_candidates(self, workspace_id: str, plan_id: str | None = None):
        from ..core.models import PlanChangeCandidate

        query = "SELECT payload FROM plan_change_candidates WHERE workspace_id = ?"
        params: list[str] = [workspace_id]
        if plan_id:
            query += " AND plan_id = ?"
            params.append(plan_id)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [PlanChangeCandidate.model_validate_json(row["payload"]) for row in rows]

    def get_plan_by_id(self, plan_id: str) -> tuple[str, LearningPlan] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT workspace_id, payload FROM learning_plan
                WHERE plan_id = ?
                LIMIT 1
                """,
                (plan_id,),
            ).fetchone()
        if not row:
            return None
        return str(row["workspace_id"]), LearningPlan.model_validate_json(row["payload"])

    # Project identity and provisioning ------------------------------------

    def resolve_context_id(self, context_id_or_alias: str | None) -> str | None:
        normalized = str(context_id_or_alias or "").strip()
        if not normalized:
            return None
        with self._connect() as connection:
            return self._resolve_context_id(connection, normalized)

    @staticmethod
    def _windows_workspace_alias_key(alias: str) -> str | None:
        normalized = alias.strip()
        if not WINDOWS_WORKSPACE_ALIAS_PATTERN.match(normalized):
            return None
        return normalized.casefold()

    @classmethod
    def _resolve_workspace_alias_context(
        cls,
        connection: sqlite3.Connection,
        alias: str,
    ) -> str | None:
        windows_key = cls._windows_workspace_alias_key(alias)
        if windows_key is None:
            row = connection.execute(
                "SELECT context_id FROM workspace_context_aliases WHERE alias = ? LIMIT 1",
                (alias,),
            ).fetchone()
            return str(row["context_id"]) if row is not None else None

        matches = {
            str(row["context_id"])
            for row in connection.execute(
                "SELECT alias, context_id FROM workspace_context_aliases"
            ).fetchall()
            if cls._windows_workspace_alias_key(str(row["alias"])) == windows_key
        }
        if len(matches) > 1:
            raise ValueError("Conflicting case-insensitive Windows workspace aliases.")
        return next(iter(matches), None)

    @classmethod
    def _ensure_workspace_alias_available(
        cls,
        connection: sqlite3.Connection,
        alias: str,
        context_id: str,
    ) -> None:
        existing_context_id = cls._resolve_workspace_alias_context(connection, alias)
        if existing_context_id is not None and existing_context_id != context_id:
            raise ValueError("The legacy workspace alias already belongs to another context.")

    @classmethod
    def _resolve_context_id(cls, connection: sqlite3.Connection, context_id_or_alias: str) -> str | None:
        context = connection.execute(
            "SELECT context_id FROM project_contexts WHERE context_id = ? LIMIT 1",
            (context_id_or_alias,),
        ).fetchone()
        if context is not None:
            return str(context["context_id"])
        return cls._resolve_workspace_alias_context(connection, context_id_or_alias)

    def get_trainer_root(self, root_id: str) -> TrainerRoot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM trainer_roots WHERE root_id = ? LIMIT 1",
                (root_id,),
            ).fetchone()
        return TrainerRoot.model_validate_json(row["payload"]) if row else None

    def get_trainer_root_by_path(self, root_path: str) -> TrainerRoot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM trainer_roots WHERE root_path = ? LIMIT 1",
                (root_path,),
            ).fetchone()
        return TrainerRoot.model_validate_json(row["payload"]) if row else None

    def create_trainer_root(self, root_path: str) -> TrainerRoot:
        normalized_path = str(Path(root_path).expanduser().resolve(strict=False))
        root = TrainerRoot(
            rootId=f"root-{uuid4().hex}",
            rootPath=normalized_path,
            displayName=Path(normalized_path).name or "Trainer Workspace",
        )
        return self.register_trainer_root(root)

    def register_trainer_root(self, root: TrainerRoot) -> TrainerRoot:
        """Persist a selected root without creating a project or bypassing authority."""
        with self._connect() as connection:
            by_id = connection.execute(
                "SELECT payload FROM trainer_roots WHERE root_id = ? LIMIT 1",
                (root.root_id,),
            ).fetchone()
            by_path = connection.execute(
                "SELECT root_id, payload FROM trainer_roots WHERE root_path = ? LIMIT 1",
                (root.root_path,),
            ).fetchone()
            if by_id is not None:
                current = TrainerRoot.model_validate_json(by_id["payload"])
                if by_path is not None and str(by_path["root_id"]) != root.root_id:
                    raise ValueError("Another Trainer root already owns this path.")
                return current if current.root_path == root.root_path else self.reconcile_trainer_root(root.root_id, root.root_path)
            if by_path is not None:
                return TrainerRoot.model_validate_json(by_path["payload"])
            connection.execute(
                "INSERT INTO trainer_roots (root_id, root_path, payload) VALUES (?, ?, ?)",
                (root.root_id, root.root_path, root.model_dump_json()),
            )
        return root

    def get_trainer_project(self, project_id: str) -> TrainerProject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM trainer_projects WHERE project_id = ? LIMIT 1",
                (project_id,),
            ).fetchone()
        return TrainerProject.model_validate_json(row["payload"]) if row else None

    def get_trainer_project_by_path(self, root_id: str, project_path: str) -> TrainerProject | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM trainer_projects
                WHERE root_id = ? AND project_path = ?
                LIMIT 1
                """,
                (root_id, project_path),
            ).fetchone()
        return TrainerProject.model_validate_json(row["payload"]) if row else None

    def list_trainer_projects(self, root_id: str) -> list[TrainerProject]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM trainer_projects WHERE root_id = ? ORDER BY rowid ASC",
                (root_id,),
            ).fetchall()
        return [TrainerProject.model_validate_json(row["payload"]) for row in rows]

    def get_project_context(self, context_id_or_alias: str) -> ProjectContext | None:
        with self._connect() as connection:
            context_id = self._resolve_context_id(connection, context_id_or_alias)
            if context_id is None:
                return None
            row = connection.execute(
                "SELECT payload FROM project_contexts WHERE context_id = ? LIMIT 1",
                (context_id,),
            ).fetchone()
        return ProjectContext.model_validate_json(row["payload"]) if row else None

    def get_project_context_for_project(self, project_id: str) -> ProjectContext | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM project_contexts WHERE project_id = ? LIMIT 1",
                (project_id,),
            ).fetchone()
        return ProjectContext.model_validate_json(row["payload"]) if row else None

    def list_context_aliases(self, context_id_or_alias: str) -> list[str]:
        with self._connect() as connection:
            context_id = self._resolve_context_id(connection, context_id_or_alias)
            if context_id is None:
                return []
            rows = connection.execute(
                """
                SELECT alias FROM workspace_context_aliases
                WHERE context_id = ?
                ORDER BY created_at ASC, alias ASC
                """,
                (context_id,),
            ).fetchall()
        return [str(row["alias"]) for row in rows]

    def get_project_provisioning(self, context_id_or_alias: str) -> ProjectProvisioning | None:
        with self._connect() as connection:
            context_id = self._resolve_context_id(connection, context_id_or_alias)
            if context_id is None:
                return None
            return self._load_project_provisioning(connection, context_id)

    @staticmethod
    def _load_project_provisioning(
        connection: sqlite3.Connection,
        context_id: str,
    ) -> ProjectProvisioning | None:
        row = connection.execute(
            """
            SELECT
                contexts.payload AS context_payload,
                roots.payload AS root_payload,
                projects.payload AS project_payload
            FROM project_contexts AS contexts
            JOIN trainer_roots AS roots ON roots.root_id = contexts.root_id
            JOIN trainer_projects AS projects ON projects.project_id = contexts.project_id
            WHERE contexts.context_id = ?
            LIMIT 1
            """,
            (context_id,),
        ).fetchone()
        if row is None:
            return None
        context = ProjectContext.model_validate_json(row["context_payload"])
        root = TrainerRoot.model_validate_json(row["root_payload"])
        project = TrainerProject.model_validate_json(row["project_payload"])
        return ProjectProvisioning(
            contextId=context.context_id,
            rootId=context.root_id,
            projectId=context.project_id,
            projectMemoryId=context.project_memory_id,
            projectPlanId=context.project_plan_id,
            projectTrainingId=context.project_training_id,
            projectAgentContextId=context.project_agent_context_id,
            agentSessionId=context.agent_session_id,
            legacyWorkspaceId=context.legacy_workspace_id,
            globalPlanId=context.global_plan_id,
            status=context.status,
            revision=context.revision,
            createdAt=context.created_at,
            updatedAt=context.updated_at,
            workspaceId=context.context_id,
            rootPath=root.root_path,
            projectPath=project.project_path,
            projectName=project.project_name,
            rootRevision=root.revision,
            projectRevision=project.revision,
        )

    def create_project_context_bundle(
        self,
        *,
        root: TrainerRoot,
        project: TrainerProject,
        context: ProjectContext,
        profile: UserProfile,
        plan: LearningPlan | None,
        structured_memory: dict[str, Any],
        session_payload: dict[str, Any],
        global_plan_link: GlobalPlanProjectLink | None = None,
    ) -> ProjectProvisioning:
        """Persist one Root/Project/Context and its lane state atomically."""

        if project.root_id != root.root_id:
            raise ValueError("Project does not belong to the supplied Trainer root.")
        if context.root_id != root.root_id or context.project_id != project.project_id:
            raise ValueError("Project context does not match the supplied Root/Project identity.")
        if plan is not None and plan.id != context.project_plan_id:
            raise ValueError("Project plan identity does not match the project context.")
        if str(session_payload.get("session_id") or "").strip() != context.agent_session_id:
            raise ValueError("Project session identity does not match the project context.")
        if str(session_payload.get("workspace_id") or "").strip() != context.context_id:
            raise ValueError("Project session must be stored under its context ID.")
        if global_plan_link is not None and (
            global_plan_link.workspace_id != context.context_id
            or global_plan_link.project_plan_id != context.project_plan_id
            or global_plan_link.global_plan_id != context.global_plan_id
        ):
            raise ValueError("Global-plan link does not match the project context.")

        root_payload = root.model_dump_json()
        project_payload = project.model_dump_json()
        context_payload = context.model_dump_json()
        profile_payload = profile.model_dump_json()
        plan_payload = plan.model_dump_json() if plan is not None else None
        structured_payload = json.dumps(structured_memory)
        session_serialized = json.dumps(session_payload)
        link_payload = global_plan_link.model_dump_json() if global_plan_link is not None else None

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT context_id FROM project_contexts WHERE project_id = ? LIMIT 1",
                (project.project_id,),
            ).fetchone()
            if existing is not None:
                loaded = self._load_project_provisioning(connection, str(existing["context_id"]))
                if loaded is None:
                    raise RuntimeError("Existing project context is incomplete.")
                if loaded.root_id != root.root_id or loaded.project_id != project.project_id:
                    raise ValueError("Project identity conflicts with an existing context.")
                return loaded

            root_path_conflict = connection.execute(
                "SELECT root_id FROM trainer_roots WHERE root_path = ? LIMIT 1",
                (root.root_path,),
            ).fetchone()
            if root_path_conflict is not None and str(root_path_conflict["root_id"]) != root.root_id:
                raise ValueError("A different Trainer root already owns this path.")
            connection.execute(
                """
                INSERT INTO trainer_roots (root_id, root_path, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(root_id) DO NOTHING
                """,
                (root.root_id, root.root_path, root_payload),
            )
            project_path_conflict = connection.execute(
                """
                SELECT project_id FROM trainer_projects
                WHERE root_id = ? AND project_path = ?
                LIMIT 1
                """,
                (project.root_id, project.project_path),
            ).fetchone()
            if project_path_conflict is not None and str(project_path_conflict["project_id"]) != project.project_id:
                raise ValueError("A different project already owns this path under the Trainer root.")
            connection.execute(
                """
                INSERT INTO trainer_projects (project_id, root_id, project_path, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id) DO NOTHING
                """,
                (project.project_id, project.root_id, project.project_path, project_payload),
            )
            if context.legacy_workspace_id:
                self._ensure_workspace_alias_available(
                    connection,
                    context.legacy_workspace_id,
                    context.context_id,
                )
            connection.execute(
                """
                INSERT INTO project_contexts (
                    context_id, root_id, project_id, legacy_workspace_id, payload
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    context.context_id,
                    context.root_id,
                    context.project_id,
                    context.legacy_workspace_id,
                    context_payload,
                ),
            )
            if context.legacy_workspace_id:
                connection.execute(
                    """
                    INSERT INTO workspace_context_aliases (alias, context_id, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(alias) DO NOTHING
                    """,
                    (context.legacy_workspace_id, context.context_id, context.created_at),
                )
            connection.execute(
                """
                INSERT INTO user_profile (workspace_id, payload)
                VALUES (?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET payload = excluded.payload
                """,
                (context.context_id, profile_payload),
            )
            if plan is not None and plan_payload is not None:
                connection.execute(
                    """
                    INSERT INTO learning_plan (plan_id, workspace_id, payload)
                    VALUES (?, ?, ?)
                    """,
                    (plan.id, context.context_id, plan_payload),
                )
            connection.execute(
                """
                INSERT INTO structured_memory (workspace_id, payload)
                VALUES (?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET payload = excluded.payload
                """,
                (context.context_id, structured_payload),
            )
            connection.execute(
                """
                INSERT INTO sessions (session_id, workspace_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    payload = excluded.payload
                """,
                (context.agent_session_id, context.context_id, session_serialized),
            )
            if global_plan_link is not None and link_payload is not None:
                connection.execute(
                    """
                    INSERT INTO global_plan_project_links (
                        global_plan_id, workspace_id, project_plan_id, payload
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(global_plan_id, workspace_id) DO UPDATE SET
                        project_plan_id = excluded.project_plan_id,
                        payload = excluded.payload
                    """,
                    (
                        global_plan_link.global_plan_id,
                        global_plan_link.workspace_id,
                        global_plan_link.project_plan_id,
                        link_payload,
                    ),
                )
            loaded = self._load_project_provisioning(connection, context.context_id)
            if loaded is None:
                raise RuntimeError("Project context could not be read after creation.")
            return loaded

    def reconcile_trainer_root(self, root_id: str, root_path: str) -> TrainerRoot:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM trainer_roots WHERE root_id = ? LIMIT 1",
                (root_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Trainer root was not found.")
            current = TrainerRoot.model_validate_json(row["payload"])
            history = list(dict.fromkeys([*current.path_history, current.root_path]))
            updated = current.model_copy(
                update={
                    "root_path": root_path,
                    "path_history": [item for item in history if item != root_path][-24:],
                    "revision": current.revision + 1,
                    "updated_at": utc_now_iso(),
                }
            )
            conflict = connection.execute(
                "SELECT root_id FROM trainer_roots WHERE root_path = ? LIMIT 1",
                (root_path,),
            ).fetchone()
            if conflict is not None and str(conflict["root_id"]) != root_id:
                raise ValueError("Another Trainer root already owns this path.")
            connection.execute(
                "UPDATE trainer_roots SET root_path = ?, payload = ? WHERE root_id = ?",
                (updated.root_path, updated.model_dump_json(), root_id),
            )
        return updated

    def reconcile_project_location(
        self,
        *,
        root_id: str,
        project_id: str,
        project_path: str,
        project_name: str | None = None,
    ) -> TrainerProject:
        with self._connect() as connection:
            root_row = connection.execute(
                "SELECT payload FROM trainer_roots WHERE root_id = ? LIMIT 1",
                (root_id,),
            ).fetchone()
            if root_row is None:
                raise KeyError("Trainer root was not found.")
            root = TrainerRoot.model_validate_json(root_row["payload"])
            try:
                Path(project_path).relative_to(Path(root.root_path))
            except ValueError as exc:
                raise ValueError("Project location must stay inside its Trainer root.") from exc
            row = connection.execute(
                "SELECT payload FROM trainer_projects WHERE project_id = ? AND root_id = ? LIMIT 1",
                (project_id, root_id),
            ).fetchone()
            if row is None:
                raise KeyError("Trainer project was not found.")
            current = TrainerProject.model_validate_json(row["payload"])
            history = list(dict.fromkeys([*current.path_history, current.project_path]))
            updated = current.model_copy(
                update={
                    "project_path": project_path,
                    "project_name": (project_name or current.project_name).strip() or current.project_name,
                    "path_history": [item for item in history if item != project_path][-24:],
                    "revision": current.revision + 1,
                    "updated_at": utc_now_iso(),
                }
            )
            conflict = connection.execute(
                """
                SELECT project_id FROM trainer_projects
                WHERE root_id = ? AND project_path = ?
                LIMIT 1
                """,
                (root_id, project_path),
            ).fetchone()
            if conflict is not None and str(conflict["project_id"]) != project_id:
                raise ValueError("Another project already owns this path under the Trainer root.")
            connection.execute(
                """
                UPDATE trainer_projects
                SET project_path = ?, payload = ?
                WHERE project_id = ?
                """,
                (updated.project_path, updated.model_dump_json(), project_id),
            )
        return updated

    def _migrate_legacy_workspace_identity(self, connection: sqlite3.Connection) -> None:
        migration_id = "project-identity-v1"
        applied = connection.execute(
            "SELECT 1 FROM identity_schema_migrations WHERE migration_id = ? LIMIT 1",
            (migration_id,),
        ).fetchone()
        if applied is not None:
            return
        rows = connection.execute(
            "SELECT workspace_id, payload FROM project_provisionings ORDER BY rowid ASC"
        ).fetchall()
        for row in rows:
            legacy_workspace_id = str(row["workspace_id"])
            existing_alias = self._resolve_workspace_alias_context(connection, legacy_workspace_id)
            if existing_alias is not None:
                continue
            try:
                payload = json.loads(row["payload"])
                project_path = str(payload.get("project_path") or payload.get("projectPath") or "").strip()
                project_name = str(payload.get("project_name") or payload.get("projectName") or "").strip()
                if not project_path or not project_name:
                    raise ValueError("legacy project provisioning lacks a path or name")
                root = TrainerRoot(
                    rootId=f"root-{uuid4().hex}",
                    rootPath=project_path,
                    displayName=project_name,
                )
                project = TrainerProject(
                    projectId=f"project-{uuid4().hex}",
                    rootId=root.root_id,
                    projectPath=project_path,
                    projectName=project_name,
                )
                context = ProjectContext(
                    contextId=f"context-{uuid4().hex}",
                    rootId=root.root_id,
                    projectId=project.project_id,
                    projectMemoryId=str(payload.get("project_memory_id") or payload.get("projectMemoryId") or "").strip(),
                    projectPlanId=str(payload.get("project_plan_id") or payload.get("projectPlanId") or "").strip(),
                    projectTrainingId=str(payload.get("project_training_id") or payload.get("projectTrainingId") or "").strip(),
                    projectAgentContextId=str(
                        payload.get("project_agent_context_id") or payload.get("projectAgentContextId") or ""
                    ).strip(),
                    agentSessionId=str(payload.get("agent_session_id") or payload.get("agentSessionId") or "").strip(),
                    legacyWorkspaceId=legacy_workspace_id,
                    globalPlanId=payload.get("global_plan_id") or payload.get("globalPlanId"),
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError("Legacy project provisioning cannot be migrated safely.") from exc
            connection.execute(
                "INSERT INTO trainer_roots (root_id, root_path, payload) VALUES (?, ?, ?)",
                (root.root_id, root.root_path, root.model_dump_json()),
            )
            connection.execute(
                """
                INSERT INTO trainer_projects (project_id, root_id, project_path, payload)
                VALUES (?, ?, ?, ?)
                """,
                (project.project_id, project.root_id, project.project_path, project.model_dump_json()),
            )
            connection.execute(
                """
                INSERT INTO project_contexts (
                    context_id, root_id, project_id, legacy_workspace_id, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    context.context_id,
                    context.root_id,
                    context.project_id,
                    context.legacy_workspace_id,
                    context.model_dump_json(),
                ),
            )
            connection.execute(
                "INSERT INTO workspace_context_aliases (alias, context_id, created_at) VALUES (?, ?, ?)",
                (legacy_workspace_id, context.context_id, context.created_at),
            )
            self._move_workspace_storage(connection, legacy_workspace_id, context.context_id)
        connection.execute(
            "INSERT INTO identity_schema_migrations (migration_id, applied_at) VALUES (?, ?)",
            (migration_id, utc_now_iso()),
        )

    @staticmethod
    def _move_workspace_storage(
        connection: sqlite3.Connection,
        legacy_workspace_id: str,
        context_id: str,
    ) -> None:
        for table in (
            "user_profile",
            "learning_plan",
            "subplans",
            "concept_mastery",
            "attempts",
            "mistakes",
            "reflections",
            "resources",
            "resource_tombstones",
            "teaching_assets",
            "sessions",
            "structured_memory",
        ):
            connection.execute(
                f"UPDATE {table} SET workspace_id = ? WHERE workspace_id = ?",
                (context_id, legacy_workspace_id),
            )
        connection.execute(
            "UPDATE global_plan_project_links SET workspace_id = ? WHERE workspace_id = ?",
            (context_id, legacy_workspace_id),
        )
        connection.execute(
            "UPDATE asset_links SET workspace_id = ? WHERE workspace_id = ?",
            (context_id, legacy_workspace_id),
        )
        connection.execute(
            "UPDATE memory_share_grants SET source_workspace_id = ? WHERE source_workspace_id = ?",
            (context_id, legacy_workspace_id),
        )
        connection.execute(
            "UPDATE memory_share_grants SET target_workspace_id = ? WHERE target_workspace_id = ?",
            (context_id, legacy_workspace_id),
        )
        session_rows = connection.execute(
            "SELECT session_id, payload FROM sessions WHERE workspace_id = ?",
            (context_id,),
        ).fetchall()
        for row in session_rows:
            payload = json.loads(row["payload"])
            payload["workspace_id"] = context_id
            connection.execute(
                "UPDATE sessions SET payload = ? WHERE session_id = ?",
                (json.dumps(payload), row["session_id"]),
            )
        memory = connection.execute(
            "SELECT payload FROM structured_memory WHERE workspace_id = ?",
            (context_id,),
        ).fetchone()
        if memory is not None:
            payload = json.loads(memory["payload"])
            workspace = payload.get("workspace")
            if isinstance(workspace, dict):
                workspace["workspace_id"] = context_id
            connection.execute(
                "UPDATE structured_memory SET payload = ? WHERE workspace_id = ?",
                (json.dumps(payload), context_id),
            )

    # Global plan -----------------------------------------------------------

    def ensure_default_local_owner(self) -> LocalOwner:
        owner = self.get_local_owner(DEFAULT_LOCAL_OWNER_ID)
        if owner is not None:
            return owner
        owner = LocalOwner(id=DEFAULT_LOCAL_OWNER_ID, displayName=DEFAULT_LOCAL_OWNER_NAME)
        self.save_local_owner(owner)
        return owner

    def ensure_default_global_memory(self) -> GlobalMemory:
        owner = self.ensure_default_local_owner()
        memory = self.get_global_memory(owner.id)
        if memory is not None:
            return memory
        memory = GlobalMemory(ownerId=owner.id)
        self.save_global_memory(memory)
        return memory

    def save_global_memory(self, memory: GlobalMemory) -> None:
        with self._connect() as connection:
            self._require_owner(connection, memory.owner_id)
            connection.execute(
                """
                INSERT INTO global_memory (owner_id, payload)
                VALUES (?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET payload = excluded.payload
                """,
                (memory.owner_id, memory.model_dump_json()),
            )

    def get_global_memory(self, owner_id: str) -> GlobalMemory | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM global_memory WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return GlobalMemory.model_validate_json(row["payload"]) if row else None

    def save_global_plan(self, plan: GlobalPlan) -> None:
        with self._connect() as connection:
            self._require_owner(connection, plan.owner_id)
            existing = connection.execute(
                "SELECT global_plan_id FROM global_plans WHERE owner_id = ?",
                (plan.owner_id,),
            ).fetchone()
            if existing is not None and str(existing["global_plan_id"]) != plan.id:
                raise ValueError("A local owner cannot replace a global plan identity.")
            connection.execute(
                """
                INSERT INTO global_plans (global_plan_id, owner_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET
                    payload = excluded.payload
                """,
                (plan.id, plan.owner_id, plan.model_dump_json()),
            )

    def get_global_plan(self, owner_id: str) -> GlobalPlan | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM global_plans
                WHERE owner_id = ?
                LIMIT 1
                """,
                (owner_id,),
            ).fetchone()
        return GlobalPlan.model_validate_json(row["payload"]) if row else None

    def get_default_global_plan(self) -> GlobalPlan | None:
        return self.get_global_plan(DEFAULT_LOCAL_OWNER_ID)

    def save_global_plan_project_link(self, link: GlobalPlanProjectLink) -> None:
        with self._connect() as connection:
            global_plan = connection.execute(
                "SELECT 1 FROM global_plans WHERE global_plan_id = ?",
                (link.global_plan_id,),
            ).fetchone()
            if global_plan is None:
                raise KeyError(f"Unknown global plan: {link.global_plan_id}")
            project_plan = connection.execute(
                "SELECT workspace_id FROM learning_plan WHERE plan_id = ?",
                (link.project_plan_id,),
            ).fetchone()
            if project_plan is None:
                raise KeyError(f"Unknown project plan: {link.project_plan_id}")
            if str(project_plan["workspace_id"]) != link.workspace_id:
                raise ValueError("Project plan does not belong to the requested workspace.")
            connection.execute(
                """
                INSERT INTO global_plan_project_links (
                    global_plan_id,
                    workspace_id,
                    project_plan_id,
                    payload
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(global_plan_id, workspace_id) DO UPDATE SET
                    project_plan_id = excluded.project_plan_id,
                    payload = excluded.payload
                """,
                (
                    link.global_plan_id,
                    link.workspace_id,
                    link.project_plan_id,
                    link.model_dump_json(),
                ),
            )

    def get_global_plan_project_link(
        self,
        global_plan_id: str,
        workspace_id: str,
        project_plan_id: str | None = None,
    ) -> GlobalPlanProjectLink | None:
        with self._connect() as connection:
            if project_plan_id is None:
                row = connection.execute(
                    """
                    SELECT payload FROM global_plan_project_links
                    WHERE global_plan_id = ? AND workspace_id = ?
                    LIMIT 1
                    """,
                    (global_plan_id, workspace_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT payload FROM global_plan_project_links
                    WHERE global_plan_id = ? AND workspace_id = ? AND project_plan_id = ?
                    LIMIT 1
                    """,
                    (global_plan_id, workspace_id, project_plan_id),
                ).fetchone()
        return GlobalPlanProjectLink.model_validate_json(row["payload"]) if row else None

    def list_global_plan_project_links(self, global_plan_id: str) -> list[GlobalPlanProjectLink]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM global_plan_project_links
                WHERE global_plan_id = ?
                ORDER BY rowid ASC
                """,
                (global_plan_id,),
            ).fetchall()
        return [GlobalPlanProjectLink.model_validate_json(row["payload"]) for row in rows]

    def delete_global_plan_project_link(self, global_plan_id: str, workspace_id: str) -> bool:
        with self._connect() as connection:
            deleted = connection.execute(
                """
                DELETE FROM global_plan_project_links
                WHERE global_plan_id = ? AND workspace_id = ?
                """,
                (global_plan_id, workspace_id),
            )
        return bool(deleted.rowcount)

    def save_subplan(self, plan_id: str, subplan: SubPlan) -> None:
        with self._connect() as connection:
            parent = connection.execute(
                """
                SELECT workspace_id FROM learning_plan
                WHERE plan_id = ?
                LIMIT 1
                """,
                (plan_id,),
            ).fetchone()
            if parent is None:
                raise ValueError(f"Learning plan '{plan_id}' was not found.")
            workspace_id = str(parent["workspace_id"])
            existing = connection.execute(
                """
                SELECT parent_plan_id, workspace_id FROM subplans
                WHERE subplan_id = ?
                LIMIT 1
                """,
                (subplan.id,),
            ).fetchone()
            if existing is not None and (
                str(existing["parent_plan_id"]) != plan_id
                or str(existing["workspace_id"]) != workspace_id
            ):
                raise ValueError(f"Sub-plan '{subplan.id}' belongs to a different learning plan.")
            connection.execute(
                """
                INSERT INTO subplans (subplan_id, parent_plan_id, workspace_id, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(subplan_id) DO UPDATE SET payload = excluded.payload
                """,
                (subplan.id, plan_id, workspace_id, subplan.model_dump_json()),
            )

    def get_subplan(self, plan_id: str, subplan_id: str) -> SubPlan | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM subplans
                WHERE parent_plan_id = ? AND subplan_id = ?
                LIMIT 1
                """,
                (plan_id, subplan_id),
            ).fetchone()
        return SubPlan.model_validate_json(row["payload"]) if row else None

    def list_subplans(self, plan_id: str) -> list[SubPlan]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM subplans
                WHERE parent_plan_id = ?
                ORDER BY rowid ASC
                """,
                (plan_id,),
            ).fetchall()
        return [SubPlan.model_validate_json(row["payload"]) for row in rows]

    def delete_subplan(self, plan_id: str, subplan_id: str) -> bool:
        with self._connect() as connection:
            deleted = connection.execute(
                """
                DELETE FROM subplans
                WHERE parent_plan_id = ? AND subplan_id = ?
                """,
                (plan_id, subplan_id),
            )
        return bool(deleted.rowcount)

    def save_resource(self, workspace_id: str, resource: ResourceRecord) -> None:
        with self._connect() as connection:
            payload = resource.model_dump_json()
            updated = connection.execute(
                """
                UPDATE resources
                SET payload = ?
                WHERE workspace_id = ? AND resource_id = ?
                """,
                (payload, workspace_id, resource.id),
            )
            if updated.rowcount and updated.rowcount > 0:
                return
            connection.execute(
                """
                INSERT INTO resources (resource_id, workspace_id, payload)
                VALUES (?, ?, ?)
                """,
                (resource.id, workspace_id, payload),
            )

    def list_resources(self, workspace_id: str) -> list[ResourceRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM resources WHERE workspace_id = ? ORDER BY rowid DESC",
                (workspace_id,),
            ).fetchall()
        return [ResourceRecord.model_validate_json(row["payload"]) for row in rows]

    def get_resource(self, workspace_id: str, resource_id: str) -> ResourceRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM resources
                WHERE workspace_id = ? AND resource_id = ?
                LIMIT 1
                """,
                (workspace_id, resource_id),
            ).fetchone()
        return ResourceRecord.model_validate_json(row["payload"]) if row else None

    def delete_resource(self, workspace_id: str, resource_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM resources
                WHERE workspace_id = ? AND resource_id = ?
                """,
                (workspace_id, resource_id),
            )
            connection.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def archive_and_delete_resource(
        self,
        workspace_id: str,
        resource: ResourceRecord,
        *,
        deletion_payload: dict[str, Any],
        deleted_at: str,
    ) -> bool:
        """Move a resource record into durable Trash metadata in one SQLite transaction."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO resource_tombstones (
                    workspace_id, resource_id, payload, deletion_payload, deleted_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, resource_id) DO UPDATE SET
                    payload = excluded.payload,
                    deletion_payload = excluded.deletion_payload,
                    deleted_at = excluded.deleted_at
                """,
                (
                    workspace_id,
                    resource.id,
                    resource.model_dump_json(),
                    json.dumps(deletion_payload, default=str, sort_keys=True),
                    deleted_at,
                ),
            )
            cursor = connection.execute(
                """
                DELETE FROM resources
                WHERE workspace_id = ? AND resource_id = ?
                """,
                (workspace_id, resource.id),
            )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def get_deleted_resource(
        self,
        workspace_id: str,
        resource_id: str,
    ) -> tuple[ResourceRecord, dict[str, Any]] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload, deletion_payload
                FROM resource_tombstones
                WHERE workspace_id = ? AND resource_id = ?
                LIMIT 1
                """,
                (workspace_id, resource_id),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["deletion_payload"]))
        return ResourceRecord.model_validate_json(row["payload"]), payload if isinstance(payload, dict) else {}

    def list_deleted_resources(self, workspace_id: str) -> list[tuple[ResourceRecord, str]]:
        """Return only tombstones owned by the requested workspace."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload, deleted_at
                FROM resource_tombstones
                WHERE workspace_id = ?
                ORDER BY deleted_at DESC, resource_id ASC
                """,
                (workspace_id,),
            ).fetchall()
        return [
            (ResourceRecord.model_validate_json(row["payload"]), str(row["deleted_at"]))
            for row in rows
        ]

    def restore_deleted_resource(
        self,
        workspace_id: str,
        resource: ResourceRecord,
    ) -> bool:
        """Reactivate a tombstoned resource only after its sandbox artifacts are restored."""
        with self._connect() as connection:
            tombstone = connection.execute(
                """
                SELECT 1 FROM resource_tombstones
                WHERE workspace_id = ? AND resource_id = ?
                """,
                (workspace_id, resource.id),
            ).fetchone()
            if tombstone is None:
                return False
            existing = connection.execute(
                """
                SELECT 1 FROM resources
                WHERE workspace_id = ? AND resource_id = ?
                """,
                (workspace_id, resource.id),
            ).fetchone()
            if existing is not None:
                raise ValueError("A resource with this identifier is already active.")
            connection.execute(
                """
                INSERT INTO resources (resource_id, workspace_id, payload)
                VALUES (?, ?, ?)
                """,
                (resource.id, workspace_id, resource.model_dump_json()),
            )
            connection.execute(
                """
                DELETE FROM resource_tombstones
                WHERE workspace_id = ? AND resource_id = ?
                """,
                (workspace_id, resource.id),
            )
        return True

    # Asset registry ---------------------------------------------------------

    def save_local_owner(self, owner: LocalOwner) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO local_owners (owner_id, payload)
                VALUES (?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET payload = excluded.payload
                """,
                (owner.id, owner.model_dump_json()),
            )

    def get_local_owner(self, owner_id: str) -> LocalOwner | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM local_owners WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return LocalOwner.model_validate_json(row["payload"]) if row else None

    def list_local_owners(self) -> list[LocalOwner]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM local_owners ORDER BY rowid DESC"
            ).fetchall()
        return [LocalOwner.model_validate_json(row["payload"]) for row in rows]

    def delete_local_owner(self, owner_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM global_memory WHERE owner_id = ?", (owner_id,))
            global_plan_rows = connection.execute(
                "SELECT global_plan_id FROM global_plans WHERE owner_id = ?",
                (owner_id,),
            ).fetchall()
            global_plan_ids = [str(row["global_plan_id"]) for row in global_plan_rows]
            if global_plan_ids:
                placeholders = ",".join("?" for _ in global_plan_ids)
                connection.execute(
                    f"DELETE FROM global_plan_project_links WHERE global_plan_id IN ({placeholders})",
                    global_plan_ids,
                )
                connection.execute(
                    "DELETE FROM global_plans WHERE owner_id = ?",
                    (owner_id,),
                )
            asset_rows = connection.execute(
                "SELECT asset_id FROM library_assets WHERE owner_id = ?",
                (owner_id,),
            ).fetchall()
            asset_ids = [str(row["asset_id"]) for row in asset_rows]
            if asset_ids:
                placeholders = ",".join("?" for _ in asset_ids)
                connection.execute(
                    f"DELETE FROM asset_links WHERE owner_id = ? OR asset_id IN ({placeholders})",
                    [owner_id, *asset_ids],
                )
                connection.execute(
                    f"DELETE FROM asset_revisions WHERE owner_id = ? OR asset_id IN ({placeholders})",
                    [owner_id, *asset_ids],
                )
                connection.execute(
                    "DELETE FROM library_assets WHERE owner_id = ?",
                    (owner_id,),
                )
            cursor = connection.execute(
                "DELETE FROM local_owners WHERE owner_id = ?",
                (owner_id,),
            )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def save_library_asset(self, asset: LibraryAsset) -> None:
        with self._connect() as connection:
            self._require_owner(connection, asset.owner_id)
            existing = connection.execute(
                "SELECT owner_id, payload FROM library_assets WHERE asset_id = ?",
                (asset.id,),
            ).fetchone()
            if existing is not None and str(existing["owner_id"]) != asset.owner_id:
                raise PermissionError("Library asset belongs to a different local owner.")
            if existing is not None and asset.current_revision_id is None:
                existing_asset = LibraryAsset.model_validate_json(existing["payload"])
                if existing_asset.current_revision_id:
                    asset = asset.model_copy(
                        update={"current_revision_id": existing_asset.current_revision_id}
                    )
            connection.execute(
                """
                INSERT INTO library_assets (
                    asset_id, owner_id, asset_type, scope, project_id, context_id, status, deleted_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    asset_type = excluded.asset_type,
                    scope = excluded.scope,
                    project_id = excluded.project_id,
                    context_id = excluded.context_id,
                    status = excluded.status,
                    deleted_at = excluded.deleted_at,
                    payload = excluded.payload
                """,
                (
                    asset.id,
                    asset.owner_id,
                    asset.asset_type,
                    asset.scope,
                    asset.project_id,
                    asset.context_id,
                    asset.status,
                    asset.deleted_at,
                    asset.model_dump_json(),
                ),
            )

    def get_library_asset(self, owner_id: str, asset_id: str) -> LibraryAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM library_assets WHERE owner_id = ? AND asset_id = ?",
                (owner_id, asset_id),
            ).fetchone()
        return LibraryAsset.model_validate_json(row["payload"]) if row else None

    def list_library_assets(
        self,
        owner_id: str,
        *,
        scope: str | None = None,
        asset_type: str | None = None,
        project_id: str | None = None,
        context_id: str | None = None,
        include_deleted: bool = False,
    ) -> list[LibraryAsset]:
        clauses = ["owner_id = ?"]
        params: list[Any] = [owner_id]
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if asset_type is not None:
            clauses.append("asset_type = ?")
            params.append(asset_type)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if context_id is not None:
            clauses.append("context_id = ?")
            params.append(context_id)
        if not include_deleted:
            clauses.append("status = 'active'")
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM library_assets WHERE {' AND '.join(clauses)} ORDER BY rowid DESC",
                params,
            ).fetchall()
        return [LibraryAsset.model_validate_json(row["payload"]) for row in rows]

    def search_library_assets(
        self,
        owner_id: str,
        query: str,
        *,
        scope: str | None = None,
        asset_type: str | None = None,
        project_id: str | None = None,
        context_id: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
    ) -> list[LibraryAsset]:
        normalized_query = query.strip().casefold()
        assets = self.list_library_assets(
            owner_id,
            scope=scope,
            asset_type=asset_type,
            project_id=project_id,
            context_id=context_id,
            include_deleted=include_deleted,
        )
        if not normalized_query:
            return assets[: max(1, min(limit, 100))]

        def score(asset: LibraryAsset) -> tuple[int, int]:
            haystacks = [asset.title, asset.canonical_source, asset.asset_type, asset.scope]
            haystacks.extend(source.ref for source in asset.source_chain)
            haystacks.extend(str(value) for value in asset.payload.values() if isinstance(value, str))
            normalized_values = [value.casefold() for value in haystacks if value]
            title_score = 0 if normalized_query in asset.title.casefold() else 1
            occurrences = sum(value.count(normalized_query) for value in normalized_values)
            return (title_score, -occurrences)

        matches = [
            asset
            for asset in assets
            if any(
                normalized_query in value.casefold()
                for value in [
                    asset.title,
                    asset.canonical_source,
                    asset.asset_type,
                    asset.scope,
                    *(source.ref for source in asset.source_chain),
                    *(str(value) for value in asset.payload.values() if isinstance(value, str)),
                ]
                if value
            )
        ]
        return sorted(matches, key=score)[: max(1, min(limit, 100))]

    def archive_library_asset(
        self,
        owner_id: str,
        asset_id: str,
        *,
        deleted_at: str,
        reason: str = "",
    ) -> LibraryAsset:
        with self._connect() as connection:
            self._require_owned_asset(connection, owner_id, asset_id)
            row = connection.execute(
                "SELECT payload FROM library_assets WHERE owner_id = ? AND asset_id = ?",
                (owner_id, asset_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown library asset: {asset_id}")
            asset = LibraryAsset.model_validate_json(row["payload"])
            if asset.status == "deleted":
                return asset
            archived = asset.model_copy(
                update={
                    "status": "deleted",
                    "deleted_at": deleted_at,
                    "deletion_reason": reason.strip(),
                    "updated_at": deleted_at,
                }
            )
            connection.execute(
                """
                UPDATE library_assets
                SET status = ?, deleted_at = ?, payload = ?
                WHERE owner_id = ? AND asset_id = ?
                """,
                (
                    archived.status,
                    archived.deleted_at,
                    archived.model_dump_json(),
                    owner_id,
                    asset_id,
                ),
            )
        return archived

    def restore_library_asset(self, owner_id: str, asset_id: str, *, restored_at: str) -> LibraryAsset:
        with self._connect() as connection:
            self._require_owned_asset(connection, owner_id, asset_id)
            row = connection.execute(
                "SELECT payload FROM library_assets WHERE owner_id = ? AND asset_id = ?",
                (owner_id, asset_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown library asset: {asset_id}")
            asset = LibraryAsset.model_validate_json(row["payload"])
            if asset.status == "active":
                return asset
            restored = asset.model_copy(
                update={
                    "status": "active",
                    "deleted_at": None,
                    "deletion_reason": "",
                    "updated_at": restored_at,
                }
            )
            connection.execute(
                """
                UPDATE library_assets
                SET status = ?, deleted_at = ?, payload = ?
                WHERE owner_id = ? AND asset_id = ?
                """,
                (
                    restored.status,
                    restored.deleted_at,
                    restored.model_dump_json(),
                    owner_id,
                    asset_id,
                ),
            )
        return restored

    def delete_library_asset(self, owner_id: str, asset_id: str) -> bool:
        with self._connect() as connection:
            self._require_owned_asset(connection, owner_id, asset_id)
            connection.execute(
                "DELETE FROM asset_links WHERE owner_id = ? AND asset_id = ?",
                (owner_id, asset_id),
            )
            connection.execute(
                "DELETE FROM asset_revisions WHERE owner_id = ? AND asset_id = ?",
                (owner_id, asset_id),
            )
            cursor = connection.execute(
                "DELETE FROM library_assets WHERE owner_id = ? AND asset_id = ?",
                (owner_id, asset_id),
            )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def save_asset_revision(self, revision: AssetRevision) -> None:
        with self._connect() as connection:
            self._require_owned_asset(connection, revision.owner_id, revision.asset_id)
            if revision.parent_revision_id == revision.id:
                raise ValueError("A revision cannot be its own parent.")
            if revision.parent_revision_id:
                parent = connection.execute(
                    """
                    SELECT 1 FROM asset_revisions
                    WHERE revision_id = ? AND owner_id = ? AND asset_id = ?
                    """,
                    (revision.parent_revision_id, revision.owner_id, revision.asset_id),
                ).fetchone()
                if parent is None:
                    raise ValueError("Parent revision must belong to the same owner and asset.")
            existing = connection.execute(
                "SELECT owner_id, asset_id, payload FROM asset_revisions WHERE revision_id = ?",
                (revision.id,),
            ).fetchone()
            if existing is not None and (
                str(existing["owner_id"]) != revision.owner_id
                or str(existing["asset_id"]) != revision.asset_id
            ):
                raise PermissionError("Asset revision belongs to a different owner or asset.")
            if existing is not None:
                persisted = AssetRevision.model_validate_json(existing["payload"])
                if persisted.model_dump(mode="json") != revision.model_dump(mode="json"):
                    raise ValueError("A retained asset revision cannot be modified in place.")
                return
            connection.execute(
                """
                INSERT INTO asset_revisions (revision_id, asset_id, owner_id, parent_revision_id, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    revision.id,
                    revision.asset_id,
                    revision.owner_id,
                    revision.parent_revision_id,
                    revision.model_dump_json(),
                ),
            )
            self._set_current_asset_revision(
                connection,
                revision.owner_id,
                revision.asset_id,
                revision.id,
                updated_at=revision.updated_at,
            )

    def get_asset_revision(
        self,
        owner_id: str,
        asset_id: str,
        revision_id: str,
    ) -> AssetRevision | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM asset_revisions
                WHERE owner_id = ? AND asset_id = ? AND revision_id = ?
                """,
                (owner_id, asset_id, revision_id),
            ).fetchone()
        return AssetRevision.model_validate_json(row["payload"]) if row else None

    def list_asset_revisions(self, owner_id: str, asset_id: str) -> list[AssetRevision]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM asset_revisions
                WHERE owner_id = ? AND asset_id = ?
                ORDER BY rowid DESC
                """,
                (owner_id, asset_id),
            ).fetchall()
        return [AssetRevision.model_validate_json(row["payload"]) for row in rows]

    def delete_asset_revision(self, owner_id: str, asset_id: str, revision_id: str) -> bool:
        with self._connect() as connection:
            self._require_owned_asset(connection, owner_id, asset_id)
            child = connection.execute(
                """
                SELECT 1 FROM asset_revisions
                WHERE owner_id = ? AND asset_id = ? AND parent_revision_id = ?
                LIMIT 1
                """,
                (owner_id, asset_id, revision_id),
            ).fetchone()
            if child is not None:
                raise ValueError("Cannot delete an asset revision that has retained descendants.")
            cursor = connection.execute(
                """
                DELETE FROM asset_revisions
                WHERE owner_id = ? AND asset_id = ? AND revision_id = ?
                """,
                (owner_id, asset_id, revision_id),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                current = connection.execute(
                    """
                    SELECT revision_id FROM asset_revisions
                    WHERE owner_id = ? AND asset_id = ?
                    ORDER BY rowid DESC
                    LIMIT 1
                    """,
                    (owner_id, asset_id),
                ).fetchone()
                replacement = str(current["revision_id"]) if current else None
                self._set_current_asset_revision(
                    connection,
                    owner_id,
                    asset_id,
                    replacement,
                )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def save_asset_link(self, link: AssetLink) -> None:
        with self._connect() as connection:
            self._require_owned_asset(connection, link.owner_id, link.asset_id)
            existing = connection.execute(
                "SELECT owner_id, asset_id FROM asset_links WHERE link_id = ?",
                (link.id,),
            ).fetchone()
            if existing is not None and (
                str(existing["owner_id"]) != link.owner_id
                or str(existing["asset_id"]) != link.asset_id
            ):
                raise PermissionError("Asset link belongs to a different owner or asset.")
            existing_relationship = connection.execute(
                """
                SELECT link_id FROM asset_links
                WHERE owner_id = ? AND asset_id = ? AND workspace_id = ?
                  AND relation = ? AND source_ref = ?
                """,
                (
                    link.owner_id,
                    link.asset_id,
                    link.workspace_id,
                    link.relation,
                    link.source_ref,
                ),
            ).fetchone()
            if existing_relationship is not None:
                link = link.model_copy(update={"id": str(existing_relationship["link_id"])})
            connection.execute(
                """
                INSERT INTO asset_links (
                    link_id, owner_id, asset_id, workspace_id, relation, source_ref, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, asset_id, workspace_id, relation, source_ref) DO UPDATE SET
                    payload = excluded.payload
                """,
                (
                    link.id,
                    link.owner_id,
                    link.asset_id,
                    link.workspace_id,
                    link.relation,
                    link.source_ref,
                    link.model_dump_json(),
                ),
            )

    def list_asset_links(
        self,
        owner_id: str,
        *,
        asset_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[AssetLink]:
        clauses = ["owner_id = ?"]
        params: list[Any] = [owner_id]
        if asset_id is not None:
            clauses.append("asset_id = ?")
            params.append(asset_id)
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM asset_links WHERE {' AND '.join(clauses)} ORDER BY rowid DESC",
                params,
            ).fetchall()
        return [AssetLink.model_validate_json(row["payload"]) for row in rows]

    def delete_asset_link(
        self,
        owner_id: str,
        asset_id: str,
        workspace_id: str,
        relation: str,
        *,
        source_ref: str = "",
    ) -> bool:
        with self._connect() as connection:
            self._require_owned_asset(connection, owner_id, asset_id)
            cursor = connection.execute(
                """
                DELETE FROM asset_links
                WHERE owner_id = ? AND asset_id = ? AND workspace_id = ?
                  AND relation = ? AND source_ref = ?
                """,
                (owner_id, asset_id, workspace_id, relation, source_ref),
            )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    @staticmethod
    def _require_owner(connection: sqlite3.Connection, owner_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM local_owners WHERE owner_id = ?",
            (owner_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown local owner: {owner_id}")

    def _require_owned_asset(
        self,
        connection: sqlite3.Connection,
        owner_id: str,
        asset_id: str,
    ) -> None:
        self._require_owner(connection, owner_id)
        row = connection.execute(
            "SELECT owner_id FROM library_assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown library asset: {asset_id}")
        if str(row["owner_id"]) != owner_id:
            raise PermissionError("Library asset belongs to a different local owner.")

    @staticmethod
    def _set_current_asset_revision(
        connection: sqlite3.Connection,
        owner_id: str,
        asset_id: str,
        revision_id: str | None,
        *,
        updated_at: str | None = None,
    ) -> None:
        row = connection.execute(
            "SELECT payload FROM library_assets WHERE owner_id = ? AND asset_id = ?",
            (owner_id, asset_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown library asset: {asset_id}")
        asset = LibraryAsset.model_validate_json(row["payload"])
        updated_asset = asset.model_copy(
            update={
                "current_revision_id": revision_id,
                "updated_at": updated_at or asset.updated_at,
            }
        )
        connection.execute(
            """
            UPDATE library_assets
            SET payload = ?
            WHERE owner_id = ? AND asset_id = ?
            """,
            (updated_asset.model_dump_json(), owner_id, asset_id),
        )

    def save_teaching_asset(self, workspace_id: str, asset: TeachingKnowledgeAsset) -> None:
        resolved_workspace_id = asset.workspace_id or workspace_id
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO teaching_assets (asset_id, workspace_id, scope, kind, source_key, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    scope = excluded.scope,
                    kind = excluded.kind,
                    source_key = excluded.source_key,
                    payload = excluded.payload
                """,
                (
                    asset.id,
                    resolved_workspace_id,
                    asset.scope,
                    asset.kind,
                    asset.source_key,
                    asset.model_dump_json(),
                ),
            )

    def list_teaching_assets(
        self,
        workspace_id: str | None = None,
        *,
        scope: str | None = None,
        kind: str | None = None,
    ) -> list[TeachingKnowledgeAsset]:
        query = "SELECT payload FROM teaching_assets"
        clauses: list[str] = []
        params: list[Any] = []
        if workspace_id is not None:
            clauses.append(
                "(workspace_id = ? OR (scope = 'general' AND workspace_id = '__global__'))"
            )
            params.append(workspace_id)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            query = f"{query} WHERE {' AND '.join(clauses)}"
        query = f"{query} ORDER BY rowid DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [TeachingKnowledgeAsset.model_validate_json(row["payload"]) for row in rows]

    def load_teaching_asset(self, asset_id: str) -> TeachingKnowledgeAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM teaching_assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        return TeachingKnowledgeAsset.model_validate_json(row["payload"]) if row else None

    def save_session(self, session_id: str, workspace_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (session_id, workspace_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET payload = excluded.payload
                """,
                (session_id, workspace_id, json.dumps(payload)),
            )

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def load_latest_session_for_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM sessions
                WHERE workspace_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def load_latest_session_by_ids(
        self,
        workspace_id: str,
        session_ids: list[str],
    ) -> dict[str, Any] | None:
        cleaned_ids = [item.strip() for item in session_ids if item and item.strip()]
        if not cleaned_ids:
            return None
        placeholders = ",".join("?" for _ in cleaned_ids)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT payload FROM sessions
                WHERE workspace_id = ? AND session_id IN ({placeholders})
                ORDER BY rowid DESC
                LIMIT 1
                """,
                [workspace_id, *cleaned_ids],
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_agent_turn_checkpoint(
        self,
        *,
        checkpoint_id: str,
        workspace_id: str,
        session_id: str,
        context_id: str,
        created_at: str,
        payload: dict[str, Any],
    ) -> None:
        """Append a durable agent trace. Checkpoints are intentionally immutable."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_turn_checkpoints (
                    checkpoint_id, workspace_id, session_id, context_id, created_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    workspace_id,
                    session_id,
                    context_id,
                    created_at,
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )

    def load_agent_turn_checkpoint(
        self,
        checkpoint_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        """Load one checkpoint only when it belongs to the requesting workspace."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM agent_turn_checkpoints
                WHERE checkpoint_id = ? AND workspace_id = ?
                LIMIT 1
                """,
                (checkpoint_id, workspace_id),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_agent_turn_checkpoints(
        self,
        workspace_id: str,
        *,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return durable checkpoints in newest-first order for one workspace."""
        normalized_limit = max(1, min(int(limit), 100))
        query = "SELECT payload FROM agent_turn_checkpoints WHERE workspace_id = ?"
        params: list[Any] = [workspace_id]
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(normalized_limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_structured_memory(self, workspace_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO structured_memory (workspace_id, payload)
                VALUES (?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET payload = excluded.payload
                """,
                (workspace_id, json.dumps(payload)),
            )

    def load_structured_memory(self, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM structured_memory WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_structured_memory(self) -> list[tuple[str, dict[str, Any]]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT workspace_id, payload FROM structured_memory
                ORDER BY rowid DESC
                """
            ).fetchall()
        return [(str(row["workspace_id"]), json.loads(row["payload"])) for row in rows]

    def save_memory_share_grant(self, grant: MemoryShareGrant) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_share_grants (source_workspace_id, target_workspace_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(source_workspace_id, target_workspace_id) DO UPDATE SET
                    payload = excluded.payload
                """,
                (
                    grant.source_workspace_id,
                    grant.target_workspace_id,
                    grant.model_dump_json(),
                ),
            )

    def get_memory_share_grant(
        self,
        source_workspace_id: str,
        target_workspace_id: str,
    ) -> MemoryShareGrant | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM memory_share_grants
                WHERE source_workspace_id = ? AND target_workspace_id = ?
                """,
                (source_workspace_id, target_workspace_id),
            ).fetchone()
        return MemoryShareGrant.model_validate_json(row["payload"]) if row else None

    def list_memory_share_grants(self, target_workspace_id: str) -> list[MemoryShareGrant]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM memory_share_grants
                WHERE target_workspace_id = ?
                ORDER BY rowid DESC
                """,
                (target_workspace_id,),
            ).fetchall()
        return [MemoryShareGrant.model_validate_json(row["payload"]) for row in rows]

    def delete_memory_share_grant(self, source_workspace_id: str, target_workspace_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_share_grants
                WHERE source_workspace_id = ? AND target_workspace_id = ?
                """,
                (source_workspace_id, target_workspace_id),
            )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def list_profiles(self) -> list[tuple[str, UserProfile]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT workspace_id, payload FROM user_profile
                ORDER BY rowid DESC
                """
            ).fetchall()
        return [
            (str(row["workspace_id"]), UserProfile.model_validate_json(row["payload"]))
            for row in rows
        ]

    def exclude_workspace_from_transfer_promotion(self, workspace_id: str) -> None:
        cleaned = workspace_id.strip()
        if not cleaned:
            return
        excluded_at = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transfer_promotion_exclusions (workspace_id, excluded_at)
                VALUES (?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET excluded_at = excluded.excluded_at
                """,
                (cleaned, excluded_at),
            )
            connection.execute(
                """
                INSERT INTO transfer_promotion_exclusion_history (workspace_id, excluded_at)
                VALUES (?, ?)
                ON CONFLICT(workspace_id) DO NOTHING
                """,
                (cleaned, excluded_at),
            )

    def include_workspace_in_transfer_promotion(self, workspace_id: str) -> None:
        cleaned = workspace_id.strip()
        if not cleaned:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM transfer_promotion_exclusions WHERE workspace_id = ?",
                (cleaned,),
            )

    def list_transfer_promotion_exclusions(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT workspace_id FROM transfer_promotion_exclusions"
            ).fetchall()
        return {str(row["workspace_id"]).strip() for row in rows if str(row["workspace_id"]).strip()}

    def list_transfer_promotion_exclusion_history(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT workspace_id FROM transfer_promotion_exclusion_history"
            ).fetchall()
        return {str(row["workspace_id"]).strip() for row in rows if str(row["workspace_id"]).strip()}
