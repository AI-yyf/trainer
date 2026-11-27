from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

from ..core.models import (
    AssetLink,
    AssetRevision,
    GlobalMemory,
    GlobalPlan,
    GlobalPlanProjectLink,
    LibraryAsset,
    LocalOwner,
    MemoryShareGrant,
    ResourceRecord,
    SubPlan,
    TeachingKnowledgeAsset,
    UserProfile,
    utc_now_iso,
)
from .repository_types import (
    DEFAULT_LOCAL_OWNER_ID,
    _merge_structured_state,
)


class RepositoryAssetsAndTransferMixin:
    if TYPE_CHECKING:
        _connect: Any

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
        updated_at = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (session_id, workspace_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (session_id, workspace_id, json.dumps(payload), updated_at),
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
                ORDER BY updated_at DESC, rowid DESC
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
                ORDER BY updated_at DESC, rowid DESC
                LIMIT 1
                """,
                [workspace_id, *cleaned_ids],
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_sessions_for_workspace(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return stored session payloads for a workspace, newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, payload FROM sessions
                WHERE workspace_id = ?
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        sessions: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                payload.setdefault("session_id", row["session_id"])
                sessions.append(payload)
        return sessions

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

    def save_structured_memory(
        self,
        workspace_id: str,
        payload: dict[str, Any],
        *,
        expected_revision: int | None = None,
        base_payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Persist one workspace's structured memory; returns ``(revision, stored)``.

        Several VS Code windows share one LibraryRoot, and each window runs its
        own sidecar — so two processes can write the same workspace. The record
        is one JSON object and each process caches its own copy, so a plain
        whole-object overwrite silences whatever the other process wrote. When
        the caller can say what its copy was based on (``base_payload``), only
        the parts of ``payload`` that differ from it are applied, recursively,
        onto the stored object; every other part keeps the stored value. The
        read and the write happen in one immediate transaction, so two sidecars
        cannot interleave between them. The revision advances on every write.
        """
        with self._connect() as connection:
            # The SELECT and the upsert must see and update one consistent row;
            # BEGIN IMMEDIATE takes the write lock before the read so a second
            # process waits here instead of writing between read and update.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, revision FROM structured_memory WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            stored = json.loads(row["payload"]) if row else None
            current_revision = int(row["revision"]) if row else 0
            revision = current_revision + 1
            merged = payload
            if stored is not None and base_payload is not None:
                merged = _merge_structured_state(base_payload, payload, stored)
            connection.execute(
                """
                INSERT INTO structured_memory (workspace_id, payload, revision)
                VALUES (?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    payload = excluded.payload,
                    revision = excluded.revision
                """,
                (workspace_id, json.dumps(merged), revision),
            )
        return revision, merged

    def load_structured_memory_entry(
        self, workspace_id: str
    ) -> tuple[dict[str, Any], int] | None:
        """The stored structured memory and its revision, or ``None``."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, revision FROM structured_memory WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["payload"]), int(row["revision"])

    def load_structured_memory(self, workspace_id: str) -> dict[str, Any] | None:
        entry = self.load_structured_memory_entry(workspace_id)
        return entry[0] if entry else None

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
