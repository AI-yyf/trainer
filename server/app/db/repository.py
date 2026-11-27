from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.models import (
    GlobalMemory,
    GlobalPlanProjectLink,
    GoalSession,
    LearningPlan,
    LocalOwner,
    ProjectContext,
    ProjectProvisioning,
    TrainerProject,
    TrainerRoot,
    UserProfile,
    utc_now_iso,
)
from .repository_assets_and_transfer_mixin import RepositoryAssetsAndTransferMixin
from .repository_types import (
    _STRUCTURED_ITEM_ID_KEYS as _STRUCTURED_ITEM_ID_KEYS,
)
from .repository_types import (
    DEFAULT_LOCAL_OWNER_ID as DEFAULT_LOCAL_OWNER_ID,
)
from .repository_types import (
    DEFAULT_LOCAL_OWNER_NAME as DEFAULT_LOCAL_OWNER_NAME,
)
from .repository_types import (
    WINDOWS_WORKSPACE_ALIAS_PATTERN as WINDOWS_WORKSPACE_ALIAS_PATTERN,
)
from .repository_types import (
    _identities as _identities,
)
from .repository_types import (
    _merge_structured_state as _merge_structured_state,
)
from .repository_types import (
    _merge_unidentified_lists as _merge_unidentified_lists,
)
from .repository_types import (
    _merge_values as _merge_values,
)
from .repository_types import (
    _structured_item_identity as _structured_item_identity,
)


class TrainerRepository(RepositoryAssetsAndTransferMixin):
    def save_provider_capability(self, cache_key: str, states: dict[str, str]) -> None:
        """Upsert observed provider capability truth (survives sidecar restarts)."""
        from datetime import UTC, datetime

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_capability (cache_key, states_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    states_json = excluded.states_json,
                    updated_at = excluded.updated_at
                """,
                (cache_key, json.dumps(states), datetime.now(UTC).isoformat()),
            )

    def list_provider_capabilities(self) -> list[tuple[str, dict[str, str]]]:
        """Most-recently-updated capability truth first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT cache_key, states_json FROM provider_capability ORDER BY updated_at DESC"
            ).fetchall()
        return [(row["cache_key"], json.loads(row["states_json"])) for row in rows]

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        # Monotonic counter bumped whenever a statement mutates rows (INSERT/
        # UPDATE/DELETE detected via sqlite total_changes delta). Consumers such
        # as MemoryService.snapshot use it as a cheap "did any persisted state
        # change" key; it never decreases for the lifetime of the repository.
        self.write_generation = 0
        self._write_generation_lock = threading.Lock()
        self._local = threading.local()
        self._connections_lock = threading.Lock()
        self._open_connections: list[tuple[int, sqlite3.Connection]] = []
        self.connection_open_count = 0
        self._initialize()

    def _reap_dead_thread_connections(self) -> None:
        alive_ids = {t.ident for t in threading.enumerate() if t.ident is not None}
        stale: list[sqlite3.Connection] = []
        with self._connections_lock:
            kept: list[tuple[int, sqlite3.Connection]] = []
            for tid, conn in self._open_connections:
                if tid in alive_ids:
                    kept.append((tid, conn))
                else:
                    stale.append(conn)
            self._open_connections = kept
        for conn in stale:
            with suppress(sqlite3.Error):
                conn.close()

    def _get_thread_connection(self) -> sqlite3.Connection:
        target_path = str(self.database_path)
        cached_conn: sqlite3.Connection | None = getattr(self._local, "connection", None)
        cached_path: str | None = getattr(self._local, "database_path", None)
        if cached_conn is not None and cached_path == target_path:
            try:
                _ = cached_conn.in_transaction
                return cached_conn
            except sqlite3.ProgrammingError:
                self._discard_thread_connection(cached_conn)
        elif cached_conn is not None:
            self._discard_thread_connection(cached_conn)

        self._reap_dead_thread_connections()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False allows deterministic cross-thread close() on shutdown
        # while threading.local() strictly confines active query execution to one thread.
        connection = sqlite3.connect(self.database_path, timeout=5.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            mode_row = connection.execute("PRAGMA journal_mode").fetchone()
            current_mode = str(mode_row[0]).strip().lower() if mode_row else ""
            if current_mode not in {"wal", "memory"}:
                connection.execute("PRAGMA journal_mode = WAL")
            if current_mode != "memory":
                connection.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.OperationalError:
            pass
        self._local.connection = connection
        self._local.database_path = target_path
        self._local.depth = 0
        tid = threading.get_ident()
        with self._connections_lock:
            self._open_connections.append((tid, connection))
            self.connection_open_count += 1
        return connection

    def _discard_thread_connection(self, connection: sqlite3.Connection | None = None) -> None:
        conn = connection or getattr(self._local, "connection", None)
        if getattr(self._local, "connection", None) is conn:
            self._local.connection = None
            self._local.database_path = None
            self._local.depth = 0
        if conn is not None:
            with self._connections_lock:
                self._open_connections = [
                    (tid, item) for tid, item in self._open_connections if item is not conn
                ]
            with suppress(sqlite3.Error):
                conn.close()

    def close(self) -> None:
        """Close all pooled thread-local SQLite connections for clean shutdown."""
        self._local.connection = None
        self._local.database_path = None
        self._local.depth = 0
        with self._connections_lock:
            conns = [conn for _, conn in self._open_connections]
            self._open_connections.clear()
        for conn in conns:
            with suppress(sqlite3.Error):
                conn.close()

    @contextmanager
    def _connect(self):
        connection = self._get_thread_connection()
        depth = int(getattr(self._local, "depth", 0))
        if depth > 0:
            sp_name = f"sp_nested_{depth}"
            connection.execute(f"SAVEPOINT {sp_name}")
            self._local.depth = depth + 1
            try:
                yield connection
                connection.execute(f"RELEASE SAVEPOINT {sp_name}")
            except BaseException:
                with suppress(sqlite3.Error):
                    connection.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    connection.execute(f"RELEASE SAVEPOINT {sp_name}")
                raise
            finally:
                self._local.depth = depth
            return

        changes_before = connection.total_changes
        self._local.depth = 1
        committed = False
        broken = False
        try:
            yield connection
            connection.commit()
            committed = True
        except sqlite3.DatabaseError:
            broken = True
            with suppress(sqlite3.Error):
                connection.rollback()
            raise
        except BaseException:
            with suppress(sqlite3.Error):
                connection.rollback()
            raise
        finally:
            self._local.depth = 0
            if committed and connection.total_changes > changes_before:
                with self._write_generation_lock:
                    self.write_generation += 1
            if broken:
                self._discard_thread_connection(connection)

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
                CREATE TABLE IF NOT EXISTS goal_sessions (
                    goal_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_goal_sessions_workspace_status
                ON goal_sessions(workspace_id, status, updated_at DESC);
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
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT ''
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
                    payload TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0
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
                CREATE TABLE IF NOT EXISTS provider_capability (
                    cache_key TEXT PRIMARY KEY,
                    states_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._migrate_library_asset_schema(connection)
            self._migrate_legacy_workspace_identity(connection)
            # Existing databases predate the structured-memory revision.
            self._ensure_column(
                connection,
                "structured_memory",
                "revision",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "sessions",
                "updated_at",
                "TEXT NOT NULL DEFAULT ''",
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_workspace_updated_at "
                "ON sessions(workspace_id, updated_at DESC)"
            )

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

    def save_goal(self, workspace_id: str, goal: GoalSession) -> None:
        """Upsert a server-owned goal session."""
        scope = (workspace_id or goal.workspace_id or "").strip()
        goal.workspace_id = scope
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO goal_sessions (goal_id, workspace_id, status, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(goal_id) DO UPDATE SET
                  workspace_id = excluded.workspace_id,
                  status = excluded.status,
                  updated_at = excluded.updated_at,
                  payload = excluded.payload
                """,
                (
                    goal.goal_id,
                    scope,
                    goal.status,
                    goal.updated_at,
                    goal.model_dump_json(),
                ),
            )

    def get_goal(self, workspace_id: str, goal_id: str) -> GoalSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM goal_sessions WHERE workspace_id = ? AND goal_id = ?",
                (workspace_id, goal_id),
            ).fetchone()
        return GoalSession.model_validate_json(row["payload"]) if row else None

    def get_current_goal(self, workspace_id: str) -> GoalSession | None:
        """Return the active focus first, else the most recently paused goal.

        Completed goals stay readable through ``list_goals`` but never surface
        as the learner's current focus.
        """
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM goal_sessions
                WHERE workspace_id = ? AND status IN ('active', 'paused')
                ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,
                         updated_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        return GoalSession.model_validate_json(row["payload"]) if row else None

    def list_goals(self, workspace_id: str) -> list[GoalSession]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM goal_sessions
                WHERE workspace_id = ?
                ORDER BY updated_at DESC
                """,
                (workspace_id,),
            ).fetchall()
        return [GoalSession.model_validate_json(row["payload"]) for row in rows]

    def mutate_goal(
        self,
        workspace_id: str,
        goal_id: str,
        mutate: Callable[[GoalSession], bool],
    ) -> GoalSession | None:
        """Atomically read-modify-write one goal.

        ``mutate`` returns True when it changed the record. SQLite's write
        lock makes activity appends and status transitions safe across
        concurrent windows.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM goal_sessions WHERE workspace_id = ? AND goal_id = ?",
                (workspace_id, goal_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            goal = GoalSession.model_validate_json(row["payload"])
            if not mutate(goal):
                connection.rollback()
                return goal
            goal.workspace_id = workspace_id
            connection.execute(
                """
                UPDATE goal_sessions
                SET status = ?, updated_at = ?, payload = ?
                WHERE workspace_id = ? AND goal_id = ?
                """,
                (
                    goal.status,
                    goal.updated_at,
                    goal.model_dump_json(),
                    workspace_id,
                    goal_id,
                ),
            )
            connection.commit()
        return goal

    @staticmethod
    def _stamp_plan_revision(plan: LearningPlan, revision: int) -> None:
        """Mirror the stored revision anchor onto the in-memory plan so
        callers (and snapshot serializations) see the real head."""
        extras = getattr(plan, "__pydantic_extra__", None)
        if isinstance(extras, dict):
            extras["_plan_revision"] = revision

    def save_plan(self, workspace_id: str, plan: LearningPlan) -> None:
        scope = (workspace_id or "").strip()
        existing = (getattr(plan, "workspace_id", None) or "").strip()
        if scope and not (existing and existing != scope):
            plan.workspace_id = existing or scope
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM learning_plan WHERE plan_id = ?",
                (plan.id,),
            ).fetchone()
            current = 0
            if row is not None:
                try:
                    current = int(json.loads(row["payload"]).get("_plan_revision", 0) or 0)
                except (TypeError, ValueError):
                    current = 0
            # Legacy unconditional write still advances the revision counter so
            # a direct save can never silently reset another window's base.
            new_revision = current + 1
            plan_payload = plan.model_dump()
            plan_payload["_plan_revision"] = new_revision
            self._stamp_plan_revision(plan, new_revision)
            connection.execute(
                """
                INSERT INTO learning_plan (plan_id, workspace_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET payload = excluded.payload
                """,
                (plan.id, scope, json.dumps(plan_payload, ensure_ascii=False, default=str)),
            )
            connection.commit()

    def get_plan_revision(self, workspace_id: str, plan_id: str) -> int:
        """Read the current plan revision for optimistic locking."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM learning_plan WHERE workspace_id = ? AND plan_id = ?",
                (workspace_id, plan_id),
            ).fetchone()
        if row is None:
            return 0
        payload = json.loads(row["payload"])
        return payload.get("_plan_revision", 0)

    def save_plan_with_revision(
        self,
        workspace_id: str,
        plan: LearningPlan,
        *,
        expected_revision: int,
        allow_legacy: bool = False,
    ) -> dict[str, Any] | None:
        """Atomically compare and write a plan revision.

        SQLite's write lock makes the revision check and UPSERT one operation;
        two windows cannot both pass the same expected revision.
        """
        scope = (workspace_id or "").strip()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT workspace_id, payload FROM learning_plan WHERE plan_id = ?",
                (plan.id,),
            ).fetchone()
            if row is not None and str(row["workspace_id"]) != scope:
                connection.rollback()
                return None
            current = 0
            if row is not None:
                payload = json.loads(row["payload"])
                current = int(payload.get("_plan_revision", 0) or 0)
            if expected_revision != current:
                connection.rollback()
                return None
            new_revision = current + 1
            plan_payload = plan.model_dump()
            plan_payload["_plan_revision"] = new_revision
            self._stamp_plan_revision(plan, new_revision)
            connection.execute(
                """
                INSERT INTO learning_plan (plan_id, workspace_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                  workspace_id = excluded.workspace_id,
                  payload = excluded.payload
                """,
                (plan.id, scope, json.dumps(plan_payload, ensure_ascii=False, default=str)),
            )
            connection.commit()
        return {"revision": new_revision}

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
