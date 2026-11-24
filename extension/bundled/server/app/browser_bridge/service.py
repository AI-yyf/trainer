"""Pairing, Bearer credentials and the pending coach-draft queue.

Trust model (kept identical to the rest of the local sidecar): the sidecar
listens on loopback only and, when the extension manages it, every request must
carry the per-instance ``x-trainer-token``. On top of that, the browser
extension — which cannot read that instance token — authenticates with a
long-lived Bearer credential issued here:

- the host registers a 6-digit, single-use, short-lived pairing code;
- the browser extension exchanges the code once for a random credential;
- the credential is persisted (only its SHA-256 hash) in the sidecar data
  directory, so it survives restarts until it is revoked.

Zero-code auto-pairing is a convenience *on top of* that consent, never a
second way in: it mints a credential only for a browser-extension origin that
already redeemed a pairing code on this sidecar (the learner typed the code
once), or for a caller that proves the per-instance token. The Origin header is
set by the browser and cannot be forged by a web page or by another extension.

The boundary of that claim is the browser, not the host. The auto-pair route is
exempt from the instance token (the browser extension cannot read that token),
and a NATIVE process on the same machine can send any header it likes, including
a trusted extension origin. So zero-code pairing defends against web pages and
other extensions, not against a local process that already knows the paired
extension id; such a process can reach the browser lane of this loopback sidecar.
The instance token remains the boundary for everything outside the browser lane,
and revoking the pairing retires the origin for that process as well.

The pending coach-draft queue is strictly workspace-scoped: every queued draft
carries the workspace its selection was captured for (the credential's
workspace), and the host can only read/acknowledge drafts of the workspace it
polls for. A capture can therefore never surface in another project's coach.

Nothing in this module performs network fetches or library writes; the capture
pipeline itself lives in ``app.resources.capture``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

logger = logging.getLogger(__name__)

PAIR_CODE_LENGTH = 6
AUTO_PAIR_ID = "auto"
# T-0037: /browser/pair is token-exempt and the code is 6 digits, so failed
# exchanges must be capped or a local loopback process can brute-force the
# window and obtain a long-lived workspace-bound credential.
PAIR_CODE_MAX_FAILED_ATTEMPTS = 5
PAIR_CODE_DEFAULT_TTL_SECONDS = 600
PAIR_CODE_MIN_TTL_SECONDS = 30
PAIR_CODE_MAX_TTL_SECONDS = 3600
CREDENTIAL_PREFIX = "trcb_"
_STATE_FILE_NAME = "browser_bridge.json"
_STATE_VERSION = 1
# A browser sets the Origin of its own extension pages and refuses to let a
# page or an extension script choose another one, so an extension origin is
# the one claim about a browser caller the sidecar can trust. Chrome IDs are
# 32 letters a-p; Firefox uses a UUID.
_EXTENSION_ORIGIN_RE = re.compile(r"^(chrome-extension://[a-p]{32}|moz-extension://[0-9a-fA-F-]{36})$")
_MAX_TRUSTED_EXTENSION_ORIGINS = 8
# Tombstones are bounded, but far above anything a learner could outlive: a
# hash is only ever re-created by a brand-new random token.
_MAX_REVOKED_CREDENTIAL_HASHES = 512
_MAX_REVOKED_EXTENSION_ORIGINS = 64
# A trusted extension re-pairs automatically whenever the sidecar restarts
# under a new instance. Old credentials stay valid, so cap the pile instead of
# growing it forever.
_MAX_AUTO_CREDENTIALS_PER_WORKSPACE = 10
_MAX_REMEMBERED_CAPTURES = 200
_MAX_PENDING_DRAFTS = 50
_MAX_ACKED_DRAFT_IDS = 200
_DRAFT_SELECTION_LIMIT = 1200
_DRAFT_TITLE_LIMIT = 160
_DRAFT_QUESTION_LIMIT = 500
_SOURCE_KINDS = frozenset({"web", "pdf", "github_repo"})
# Workspace and client id are joined with NUL: repository paths never contain
# it, so ("ws-a", "1") and ("ws-a\01", "") cannot collide.
_DRAFT_DEDUPE_SEPARATOR = "\u0000"


class BrowserPairingError(RuntimeError):
    """A display-safe pairing failure carrying its HTTP mapping."""

    def __init__(self, code: str, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class PairCodeRegistration:
    code: str
    workspace_id: str
    workspace_name: str
    created_at: str
    expires_at: float
    expires_in: int

    def as_payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "expires_in": self.expires_in,
        }


@dataclass(frozen=True, slots=True)
class BrowserCredential:
    token_hash: str
    token_suffix: str
    workspace_id: str
    workspace_name: str
    created_at: str
    last_used_at: str | None = None
    pair_code_id: str = ""

    def as_payload(self, *, credential: str = "") -> dict[str, object]:
        payload: dict[str, object] = {
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "created_at": self.created_at,
        }
        if credential:
            payload["credential"] = credential
        return payload


@dataclass(slots=True)
class _PendingDraft:
    id: str
    workspace_id: str
    text: str
    client_id: str
    created_at: str
    url: str = ""
    title: str = ""
    selection: str = ""
    question: str = ""
    source_kind: str = ""

    def as_payload(self) -> dict[str, str]:
        result = {"id": self.id, "workspace_id": self.workspace_id, "text": self.text}
        if self.url:
            result.update(url=self.url, title=self.title, selection=self.selection)
        if self.question:
            result["question"] = self.question
        if self.source_kind and self.source_kind != "web":
            result["source_kind"] = self.source_kind
        return result


def _hashed(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_extension_origin(value: object) -> str:
    """Return the canonical browser-extension origin, or ``""`` if it is not one."""
    text = str(value or "").strip().rstrip("/").lower()
    return text if text and _EXTENSION_ORIGIN_RE.match(text) else ""


def _draft_dedupe_key(workspace_id: str, client_id: str) -> str:
    return f"{workspace_id}{_DRAFT_DEDUPE_SEPARATOR}{client_id}"


def _utc_now_iso() -> str:
    from ..core.models import utc_now_iso

    return utc_now_iso()


class BrowserBridgeService:
    """Process-wide pairing/credential/draft state for the browser lane."""

    # Touching on every request would rewrite the state file at request rate;
    # the last_used_at refresh is persisted at most this often.
    _touch_persist_interval_seconds = 60.0

    def __init__(
        self,
        data_root: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._data_root = Path(data_root)
        self._state_path = self._data_root / _STATE_FILE_NAME
        self._state_lock_path = self._data_root / f"{_STATE_FILE_NAME}.lock"
        self._clock = clock
        self._lock = threading.RLock()
        self._pair_codes: dict[str, PairCodeRegistration] = {}
        self._pair_failed_attempts = 0
        self._pair_lockout_active = False
        self._latest_pair_code_id = ""
        self._credentials: dict[str, dict[str, object]] = {}
        self._trusted_extension_origins: list[str] = []
        # Revocation tombstones. They only grow (bounded): a credential or an
        # origin retired in one sidecar process must stay retired in every
        # other process sharing this LibraryRoot, and no later write from a
        # process that still holds it in memory may bring it back.
        self._revoked_token_hashes: list[str] = []
        self._revoked_extension_origins: list[str] = []
        self._synced_stamp: tuple[int, int, int] | None = None
        self._captures: dict[str, dict[str, object]] = {}
        self._pending_drafts: list[_PendingDraft] = []
        self._acked_draft_client_ids: list[str] = []
        self._host_focus_workspace_id = ""
        self._host_focus_at = ""
        self._load_state()
        with self._lock:
            self._sync_security_state_locked(force=True)

    # ------------------------------------------------------------ persistence

    def _load_state(self) -> None:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:  # pragma: no cover - unreadable data dir
            logger.warning("Browser bridge state could not be read: %s", exc)
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Browser bridge state file is not valid JSON; starting empty.")
            return
        if not isinstance(payload, dict) or payload.get("version") != _STATE_VERSION:
            return
        credentials = payload.get("credentials")
        if isinstance(credentials, list):
            for entry in credentials:
                if not isinstance(entry, dict):
                    continue
                token_hash = str(entry.get("token_hash") or "").strip()
                workspace_id = str(entry.get("workspace_id") or "").strip()
                if not token_hash or not workspace_id:
                    continue
                self._credentials[token_hash] = {
                    "token_hash": token_hash,
                    "token_suffix": str(entry.get("token_suffix") or ""),
                    "workspace_id": workspace_id,
                    "workspace_name": str(entry.get("workspace_name") or ""),
                    "created_at": str(entry.get("created_at") or ""),
                    "last_used_at": entry.get("last_used_at") or None,
                    "pair_code_id": str(entry.get("pair_code_id") or ""),
                }
        captures = payload.get("captures")
        if isinstance(captures, dict):
            self._captures = {
                str(key): dict(value)
                for key, value in captures.items()
                if isinstance(value, dict)
            }
        raw_origins = payload.get("trusted_extension_origins")
        if isinstance(raw_origins, list):
            self._trusted_extension_origins = [
                origin
                for origin in (normalize_extension_origin(item) for item in raw_origins)
                if origin
            ][:_MAX_TRUSTED_EXTENSION_ORIGINS]
        # Accepted-but-undelivered drafts survive restarts (T-0009): they were
        # acknowledged to the browser as stored, so losing them on a sidecar
        # restart would break that promise.
        raw_drafts = payload.get("pending_drafts")
        if isinstance(raw_drafts, list):
            drafts: list[_PendingDraft] = []
            for entry in raw_drafts:
                if not isinstance(entry, dict):
                    continue
                draft_id = str(entry.get("id") or "").strip()
                workspace_id = str(entry.get("workspace_id") or "").strip()
                text = str(entry.get("text") or "")
                if not draft_id or not workspace_id or not text:
                    continue
                drafts.append(
                    _PendingDraft(
                        id=draft_id,
                        workspace_id=workspace_id,
                        text=text,
                        client_id=str(entry.get("client_id") or ""),
                        created_at=str(entry.get("created_at") or _utc_now_iso()),
                        url=str(entry.get("url") or ""),
                        title=str(entry.get("title") or ""),
                        selection=str(entry.get("selection") or ""),
                        question=str(entry.get("question") or ""),
                        source_kind=str(entry.get("source_kind") or ""),
                    )
                )
            self._pending_drafts = drafts
        raw_acked = payload.get("acked_draft_client_ids")
        if isinstance(raw_acked, list):
            self._acked_draft_client_ids = [
                str(item) for item in raw_acked if str(item).strip()
            ]

    @contextmanager
    def _state_file_lock(self) -> Iterator[None]:
        """Serialize the read-merge-replace cycle across sidecar processes.

        ``threading.RLock`` only guards one process. Two windows over one
        LibraryRoot used to be able to interleave sync and replace: the later
        writer re-serialized its stale in-memory copy and erased a revocation
        the other had just written. The OS lock makes sync + write atomic, so a
        tombstone can only be appended, never lost.
        """
        self._data_root.mkdir(parents=True, exist_ok=True)
        with open(self._state_lock_path, "a+b") as handle:
            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                # LK_LOCK retries only ten times before raising; keep waiting
                # instead of losing a revocation write under contention.
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _state_file_stamp(self) -> tuple[int, int, int] | None:
        try:
            stat = self._state_path.stat()
        except OSError:
            return None
        # os.replace swaps the inode; including it detects a same-size,
        # same-tick replacement that mtime/size alone would miss.
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    def _sync_security_state_locked(self, *, force: bool = False) -> None:
        """Fold the other sidecars' pairing state into this one.

        Several windows share one LibraryRoot, and each window runs its own
        sidecar over the same state file. A revocation in one process used to
        be invisible to the others: they kept accepting the credential, and
        their next write put it back in the file — so a lost browser was never
        really retired. Pairing state is therefore merged on every read and
        write: credentials and trusted origins are the union of what is on
        disk and what this process holds, minus the tombstones.
        """
        stamp = self._state_file_stamp()
        if not force and stamp is not None and stamp == self._synced_stamp:
            return
        self._synced_stamp = stamp
        disk_credentials: dict[str, dict[str, object]] = {}
        disk_origins: list[str] = []
        payload = None
        try:
            raw = self._state_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and payload.get("version") == _STATE_VERSION:
            entries = payload.get("credentials")
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    token_hash = str(entry.get("token_hash") or "").strip()
                    workspace_id = str(entry.get("workspace_id") or "").strip()
                    if not token_hash or not workspace_id:
                        continue
                    disk_credentials[token_hash] = {
                        "token_hash": token_hash,
                        "token_suffix": str(entry.get("token_suffix") or ""),
                        "workspace_id": workspace_id,
                        "workspace_name": str(entry.get("workspace_name") or ""),
                        "created_at": str(entry.get("created_at") or ""),
                        "last_used_at": entry.get("last_used_at") or None,
                        "pair_code_id": str(entry.get("pair_code_id") or ""),
                    }
            origins = payload.get("trusted_extension_origins")
            if isinstance(origins, list):
                disk_origins = [
                    origin
                    for origin in (normalize_extension_origin(item) for item in origins)
                    if origin
                ]
            revoked_hashes = payload.get("revoked_token_hashes")
            if isinstance(revoked_hashes, list):
                self._remember_revoked_token_hashes_locked(
                    str(item) for item in revoked_hashes
                )
            revoked_origins = payload.get("revoked_extension_origins")
            if isinstance(revoked_origins, list):
                self._remember_revoked_extension_origins_locked(
                    normalize_extension_origin(item) for item in revoked_origins
                )
        revoked_hashes = set(self._revoked_token_hashes)
        merged = dict(disk_credentials)
        merged.update(self._credentials)
        self._credentials = {
            token_hash: entry for token_hash, entry in merged.items() if token_hash not in revoked_hashes
        }
        revoked_origins = set(self._revoked_extension_origins)
        origins = list(dict.fromkeys([*disk_origins, *self._trusted_extension_origins]))
        self._trusted_extension_origins = [
            origin for origin in origins if origin not in revoked_origins
        ][-_MAX_TRUSTED_EXTENSION_ORIGINS:]

    def _remember_revoked_token_hashes_locked(self, hashes: Iterable[str]) -> None:
        for token_hash in hashes:
            token_hash = token_hash.strip()
            if token_hash and token_hash not in self._revoked_token_hashes:
                self._revoked_token_hashes.append(token_hash)
        self._revoked_token_hashes = self._revoked_token_hashes[-_MAX_REVOKED_CREDENTIAL_HASHES:]

    def _remember_revoked_extension_origins_locked(self, origins: Iterable[str]) -> None:
        for origin in origins:
            if origin and origin not in self._revoked_extension_origins:
                self._revoked_extension_origins.append(origin)
        self._revoked_extension_origins = self._revoked_extension_origins[
            -_MAX_REVOKED_EXTENSION_ORIGINS:
        ]

    def _write_state_locked(self) -> None:
        try:
            self._data_root.mkdir(parents=True, exist_ok=True)
            with self._state_file_lock():
                # Re-read under the inter-process lock: a revocation another
                # sidecar wrote since our last sync must be in this payload.
                self._sync_security_state_locked(force=True)
                payload = {
                    "version": _STATE_VERSION,
                    "credentials": list(self._credentials.values()),
                    "captures": self._captures,
                    "pending_drafts": [asdict(draft) for draft in self._pending_drafts],
                    "acked_draft_client_ids": list(self._acked_draft_client_ids),
                    "trusted_extension_origins": list(self._trusted_extension_origins),
                    "revoked_token_hashes": list(self._revoked_token_hashes),
                    "revoked_extension_origins": list(self._revoked_extension_origins),
                }
                serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
                # A unique temporary file: two processes must never write into
                # the same .tmp and replace each other's half-written JSON.
                fd, temp_name = tempfile.mkstemp(
                    prefix=f"{self._state_path.name}.",
                    suffix=".tmp",
                    dir=str(self._data_root),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(serialized)
                        handle.flush()
                        os.fsync(handle.fileno())
                    # Windows refuses the replace while another process has
                    # the destination open for reading; readers do not take
                    # the writer lock, so retry the atomic swap briefly.
                    for attempt in range(5):
                        try:
                            os.replace(temp_name, self._state_path)
                            break
                        except PermissionError:
                            if attempt == 4:
                                raise
                            time.sleep(0.02)
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
                # Held under the lock, so no peer can replace the file between
                # our replace and this stat.
                self._synced_stamp = self._state_file_stamp()
        except OSError as exc:  # pragma: no cover - unwritable data dir
            logger.warning("Browser bridge state could not be persisted: %s", exc)

    # -------------------------------------------------------------- pair codes

    def register_pair_code(
        self,
        *,
        code: str,
        workspace_id: str,
        workspace_name: str,
        expires_in: int | float | None = None,
    ) -> PairCodeRegistration:
        normalized_code = str(code or "").strip()
        if not normalized_code.isdigit() or len(normalized_code) != PAIR_CODE_LENGTH:
            raise BrowserPairingError(
                "invalid_pair_code",
                f"A pairing code must be exactly {PAIR_CODE_LENGTH} digits.",
                status_code=422,
            )
        normalized_workspace = str(workspace_id or "").strip()
        if not normalized_workspace:
            raise BrowserPairingError(
                "invalid_workspace",
                "A pairing code must be registered for a workspace.",
                status_code=422,
            )
        try:
            ttl = int(expires_in) if expires_in is not None else PAIR_CODE_DEFAULT_TTL_SECONDS
        except (TypeError, ValueError) as exc:
            raise BrowserPairingError(
                "invalid_expiry",
                "expires_in must be a whole number of seconds.",
                status_code=422,
            ) from exc
        ttl = max(PAIR_CODE_MIN_TTL_SECONDS, min(ttl, PAIR_CODE_MAX_TTL_SECONDS))
        now = self._clock()
        registration = PairCodeRegistration(
            code=normalized_code,
            workspace_id=normalized_workspace,
            workspace_name=str(workspace_name or "").strip() or normalized_workspace,
            created_at=_utc_now_iso(),
            expires_at=now + ttl,
            expires_in=ttl,
        )
        with self._lock:
            self._prune_expired_codes_locked(now)
            # Registering a new code retires every previous one: exactly one
            # live pairing window exists at a time.
            self._pair_codes = {normalized_code: registration}
            self._latest_pair_code_id = uuid4().hex[:12]
            self._pair_failed_attempts = 0
            self._pair_lockout_active = False
        return registration

    def _prune_expired_codes_locked(self, now: float) -> None:
        expired = [
            code for code, registration in self._pair_codes.items() if registration.expires_at <= now
        ]
        for code in expired:
            self._pair_codes.pop(code, None)

    def exchange_pair_code(self, code: str, *, origin: str = "") -> tuple[BrowserCredential, str]:
        """Consume a pairing code and return ``(credential, raw_token)``.

        The raw token is returned exactly once — only its SHA-256 hash is kept.
        When the caller is a browser extension, its origin becomes trusted for
        zero-code auto-pairing: typing the code once is the learner's consent
        for *that* extension to reconnect on its own afterwards.
        """
        trusted_origin = normalize_extension_origin(origin)

        normalized_code = str(code or "").strip()
        if not normalized_code:
            raise BrowserPairingError(
                "invalid_pair_code",
                "A pairing code is required.",
                status_code=422,
            )
        now = self._clock()
        with self._lock:
            registration = self._pair_codes.get(normalized_code)
            if registration is None:
                self._pair_failed_attempts += 1
                if (
                    self._pair_lockout_active
                    or (self._pair_codes and self._pair_failed_attempts >= PAIR_CODE_MAX_FAILED_ATTEMPTS)
                ):
                    # Kill the live window: the guesses were close enough to a
                    # brute force that the code must not keep accepting tries.
                    # The lockout stays honest (429, not "unknown") until a
                    # fresh code is registered in Trainer.
                    self._pair_codes = {}
                    self._pair_failed_attempts = 0
                    self._pair_lockout_active = True
                    raise BrowserPairingError(
                        "pair_attempts_exceeded",
                        "Too many failed pairing attempts. Generate a new pairing code in Trainer.",
                        status_code=429,
                    )
                raise BrowserPairingError(
                    "unknown_pair_code",
                    "This pairing code is not registered by Trainer (it may have been replaced).",
                    status_code=404,
                )
            if registration.expires_at <= now:
                self._pair_codes.pop(normalized_code, None)
                raise BrowserPairingError(
                    "expired_pair_code",
                    "This pairing code has expired. Generate a new one in Trainer.",
                    status_code=410,
                )
            # Single use: the code is consumed by this exchange.
            self._pair_codes.pop(normalized_code, None)
            self._pair_failed_attempts = 0
            self._pair_lockout_active = False
            token = f"{CREDENTIAL_PREFIX}{secrets.token_urlsafe(32)}"
            credential = BrowserCredential(
                token_hash=_hashed(token),
                token_suffix=token[-4:],
                workspace_id=registration.workspace_id,
                workspace_name=registration.workspace_name,
                created_at=_utc_now_iso(),
                pair_code_id=self._latest_pair_code_id,
            )
            self._credentials[credential.token_hash] = {
                **asdict(credential),
                "last_used_at": None,
            }
            if trusted_origin:
                self._trust_extension_origin_locked(trusted_origin)
            self._write_state_locked()
        return credential, token

    # ------------------------------------------------ trusted extension origins

    def _trust_extension_origin_locked(self, origin: str) -> None:
        # Trust is only recorded by the host or by a code exchange: the learner
        # just consented again, so an earlier revocation of this origin ends.
        self._revoked_extension_origins = [
            item for item in self._revoked_extension_origins if item != origin
        ]
        if origin in self._trusted_extension_origins:
            self._trusted_extension_origins.remove(origin)
        self._trusted_extension_origins.append(origin)
        while len(self._trusted_extension_origins) > _MAX_TRUSTED_EXTENSION_ORIGINS:
            self._trusted_extension_origins.pop(0)

    def trust_extension_origin(self, origin: str) -> bool:
        """Trust a browser-extension origin for zero-code pairing.

        Only host-authenticated callers and the pairing-code exchange record
        trust; the auto-pair routes only ever *read* the list.
        """
        normalized = normalize_extension_origin(origin)
        if not normalized:
            return False
        with self._lock:
            if normalized in self._trusted_extension_origins:
                return True
            self._trust_extension_origin_locked(normalized)
            self._write_state_locked()
        return True

    def is_trusted_extension_origin(self, origin: str) -> bool:
        normalized = normalize_extension_origin(origin)
        if not normalized:
            return False
        with self._lock:
            self._sync_security_state_locked()
            return normalized in self._trusted_extension_origins

    def trusted_extension_origins(self) -> list[str]:
        with self._lock:
            self._sync_security_state_locked()
            return list(self._trusted_extension_origins)

    # --------------------------------------------------------- host focus

    def mark_host_focus(self, workspace_id: str) -> str:
        """Record that this sidecar's Trainer window just gained focus.

        The browser extension probes every reachable sidecar before auto-pair
        and prefers the one with the newest focus signal, so a two-window setup
        binds to the window the learner is actually using.
        """
        normalized = str(workspace_id or "").strip()
        if not normalized:
            raise BrowserPairingError(
                "invalid_workspace",
                "Host focus needs a workspace.",
                status_code=422,
            )
        focused_at = _utc_now_iso()
        with self._lock:
            self._host_focus_workspace_id = normalized
            self._host_focus_at = focused_at
        return focused_at

    def host_focus_for(self, workspace_id: str) -> str:
        normalized = str(workspace_id or "").strip()
        with self._lock:
            if not normalized or self._host_focus_workspace_id != normalized:
                return ""
            return self._host_focus_at

    # --------------------------------------------------------- auto pairing

    def issue_auto_credential(
        self,
        *,
        workspace_id: str,
        workspace_name: str,
        extension_origin: str = "",
    ) -> tuple[BrowserCredential, str]:
        """Issue a long-lived workspace-bound credential without a pair code.

        The browser extension discovers the loopback sidecar and calls the
        auto-pair route. The route is the gate (loopback + an extension origin
        this sidecar already trusts, or the per-instance token); this method
        re-checks an origin-based authorization under the state lock so a
        revocation that lands between the route check and mint cannot leave a
        fresh valid credential behind. Auto-issued credentials for one
        workspace are capped: a restart under a new sidecar instance mints
        another, and the oldest unused one is retired past the cap.
        """
        normalized_workspace = str(workspace_id or "").strip()
        if not normalized_workspace:
            raise BrowserPairingError(
                "invalid_workspace",
                "Automatic pairing needs a workspace.",
                status_code=422,
            )
        normalized_origin = normalize_extension_origin(extension_origin)
        token = f"{CREDENTIAL_PREFIX}{secrets.token_urlsafe(32)}"
        credential = BrowserCredential(
            token_hash=_hashed(token),
            token_suffix=token[-4:],
            workspace_id=normalized_workspace,
            workspace_name=str(workspace_name or "").strip() or normalized_workspace,
            created_at=_utc_now_iso(),
            pair_code_id=AUTO_PAIR_ID,
        )
        with self._lock:
            if normalized_origin and not self.is_trusted_extension_origin(normalized_origin):
                raise BrowserPairingError(
                    "extension_not_paired",
                    "Pair this browser once with a pairing code from Trainer; it reconnects on its own afterwards.",
                    status_code=403,
                )
            self._credentials[credential.token_hash] = {
                **asdict(credential),
                "last_used_at": None,
            }
            self._prune_auto_credentials_locked(normalized_workspace)
            self._write_state_locked()
        return credential, token

    def _prune_auto_credentials_locked(self, workspace_id: str) -> None:
        auto_entries = [
            (str(entry.get("created_at") or ""), token_hash)
            for token_hash, entry in self._credentials.items()
            if str(entry.get("pair_code_id") or "") == AUTO_PAIR_ID
            and str(entry.get("workspace_id") or "") == workspace_id
        ]
        excess = len(auto_entries) - _MAX_AUTO_CREDENTIALS_PER_WORKSPACE
        for _, token_hash in sorted(auto_entries)[: max(excess, 0)]:
            if self._credentials.pop(token_hash, None) is not None:
                # Another sidecar may still hold this credential in memory;
                # the tombstone prevents its next write from resurrecting it.
                self._remember_revoked_token_hashes_locked([token_hash])

    # ------------------------------------------------------------ credentials

    def credential_for_token(self, token: str, *, touch: bool = True) -> BrowserCredential | None:
        normalized = str(token or "").strip()
        if not normalized:
            return None
        token_hash = _hashed(normalized)
        with self._lock:
            # A revocation in another sidecar process must be honoured here
            # before this token is accepted again.
            self._sync_security_state_locked()
            entry = self._credentials.get(token_hash)
            if entry is None:
                return None
            now_iso = _utc_now_iso()
            if touch:
                entry["last_used_at"] = now_iso
                # The token hash is what matters; last_used_at rides the
                # throttled persist below.
                self._maybe_persist_touch_locked()
            return self._credential_from_entry(entry)

    def _maybe_persist_touch_locked(self) -> None:
        now = self._clock()
        last = getattr(self, "_last_touch_persist_at", 0.0)
        if now - float(last) < self._touch_persist_interval_seconds:
            return
        self._last_touch_persist_at = now
        self._write_state_locked()

    @staticmethod
    def _credential_from_entry(entry: dict[str, object]) -> BrowserCredential:
        return BrowserCredential(
            token_hash=str(entry.get("token_hash") or ""),
            token_suffix=str(entry.get("token_suffix") or ""),
            workspace_id=str(entry.get("workspace_id") or ""),
            workspace_name=str(entry.get("workspace_name") or ""),
            created_at=str(entry.get("created_at") or ""),
            last_used_at=str(entry["last_used_at"]) if entry.get("last_used_at") else None,
            pair_code_id=str(entry.get("pair_code_id") or ""),
        )

    def revoke_token(self, token: str) -> bool:
        normalized = str(token or "").strip()
        if not normalized:
            return False
        token_hash = _hashed(normalized)
        with self._lock:
            self._sync_security_state_locked()
            removed = self._credentials.pop(token_hash, None) is not None
            if removed:
                self._remember_revoked_token_hashes_locked([token_hash])
                self._write_state_locked()
            return removed

    def revoke_registered_pairing(self) -> dict[str, object]:
        """Host-side revocation (``DELETE /browser/pair`` without a Bearer token).

        The host revokes "the pairing", not one browser credential: it drops the
        pending code and *every* browser credential — code-paired or
        auto-issued — and forgets the trusted extension origins, so a lost or
        unwanted browser can always be retired from the workbench and cannot
        pair itself again without the learner typing a new code.
        """
        with self._lock:
            self._sync_security_state_locked()
            had_pending_code = self._pair_codes != {}
            self._pair_codes = {}
            removed = list(self._credentials)
            self._credentials.clear()
            self._latest_pair_code_id = ""
            had_trusted_origins = self._trusted_extension_origins != []
            # Retire them for every sidecar over this LibraryRoot, and make
            # sure no process that still holds them in memory writes them back.
            self._remember_revoked_token_hashes_locked(removed)
            self._remember_revoked_extension_origins_locked(self._trusted_extension_origins)
            self._trusted_extension_origins = []
            if removed or had_pending_code or had_trusted_origins:
                self._write_state_locked()
            return {
                "revoked": True,
                "had_registration": had_pending_code or bool(removed) or had_trusted_origins,
                "credentials_revoked": len(removed),
            }

    def credential_count(self) -> int:
        with self._lock:
            return len(self._credentials)

    # ----------------------------------------------------------- idempotency

    def capture_replay(self, client_capture_id: str) -> dict[str, object] | None:
        key = str(client_capture_id or "").strip()
        if not key:
            return None
        with self._lock:
            entry = self._captures.get(key)
            return dict(entry) if entry is not None else None

    def remember_capture(self, client_capture_id: str, payload: dict[str, object]) -> None:
        key = str(client_capture_id or "").strip()
        if not key:
            return
        with self._lock:
            self._captures[key] = {**payload, "client_capture_id": key}
            while len(self._captures) > _MAX_REMEMBERED_CAPTURES:
                oldest = next(iter(self._captures))
                if oldest == key:
                    break
                self._captures.pop(oldest, None)
            self._write_state_locked()

    # -------------------------------------------------------- coach drafts

    def enqueue_draft(
        self,
        *,
        workspace_id: str,
        selection: str,
        url: str = "",
        title: str = "",
        client_id: str = "",
        language: str | None = None,
        question: str = "",
        source_kind: str = "",
    ) -> dict[str, object]:
        normalized_workspace = str(workspace_id or "").strip()
        if not normalized_workspace:
            raise BrowserPairingError(
                "invalid_workspace",
                "A coach draft requires the workspace its selection was captured for.",
                status_code=422,
            )
        excerpt = str(selection or "").strip()
        source_url = str(url or "").strip()
        if not source_url.lower().startswith(("https://", "http://")):
            source_url = ""
        source_title = " ".join(str(title or "").split())[:_DRAFT_TITLE_LIMIT]
        learner_question = " ".join(str(question or "").split())[:_DRAFT_QUESTION_LIMIT]
        normalized_source_kind = str(source_kind or "").strip().lower()
        if normalized_source_kind not in _SOURCE_KINDS:
            normalized_source_kind = "web"
        if not excerpt and not source_url:
            raise BrowserPairingError(
                "empty_selection",
                "A coach draft requires a non-empty selection.",
                status_code=422,
            )
        if len(excerpt) > _DRAFT_SELECTION_LIMIT:
            excerpt = excerpt[: _DRAFT_SELECTION_LIMIT - 1].rstrip() + "…"
        normalized_client_id = str(client_id or "").strip()
        with self._lock:
            if normalized_client_id:
                for draft in self._pending_drafts:
                    if (
                        draft.workspace_id == normalized_workspace
                        and draft.client_id == normalized_client_id
                    ):
                        return {"ok": True, "draft_id": draft.id, "duplicate": True}
                if (
                    _draft_dedupe_key(normalized_workspace, normalized_client_id)
                    in self._acked_draft_client_ids
                ):
                    return {"ok": True, "draft_id": "", "duplicate": True}
            if len(self._pending_drafts) >= _MAX_PENDING_DRAFTS:
                # The queue only drains through receipts from a visible
                # workbench. When it is full, refuse the new capture loudly
                # instead of silently evicting a queued (still undelivered)
                # one — a dropped capture the user cannot see is worse than a
                # visible "try again".
                raise BrowserPairingError(
                    "draft_queue_full",
                    "Trainer is already holding the maximum number of captured drafts. Open the Coach view to receive them, then capture again.",
                    status_code=429,
                )
            text = build_coach_draft_text(
                selection=excerpt,
                url=source_url,
                title=source_title,
                language=language,
                question=learner_question,
                source_kind=normalized_source_kind,
            )
            draft = _PendingDraft(
                id=f"draft-{uuid4().hex[:12]}",
                workspace_id=normalized_workspace,
                text=text,
                client_id=normalized_client_id,
                created_at=_utc_now_iso(),
                url=source_url,
                title=source_title,
                selection=excerpt,
                question=learner_question,
                source_kind=normalized_source_kind,
            )
            self._pending_drafts.append(draft)
            self._write_state_locked()
            return {"ok": True, "draft_id": draft.id, "duplicate": False}

    def pending_drafts(self, workspace_id: str) -> list[dict[str, str]]:
        normalized_workspace = str(workspace_id or "").strip()
        if not normalized_workspace:
            # Never hand a caller that did not state its workspace every
            # project's captures: an unscoped read is refused, not guessed.
            return []
        with self._lock:
            return [
                draft.as_payload()
                for draft in self._pending_drafts
                if draft.workspace_id == normalized_workspace
            ]

    def ack_drafts(self, workspace_id: str, ids: list[str]) -> int:
        normalized_workspace = str(workspace_id or "").strip()
        wanted = {str(item).strip() for item in ids if str(item).strip()}
        if not normalized_workspace or not wanted:
            return 0
        with self._lock:
            remaining: list[_PendingDraft] = []
            removed = 0
            for draft in self._pending_drafts:
                if draft.workspace_id == normalized_workspace and draft.id in wanted:
                    removed += 1
                    if draft.client_id:
                        self._acked_draft_client_ids.append(
                            _draft_dedupe_key(draft.workspace_id, draft.client_id)
                        )
                        if len(self._acked_draft_client_ids) > _MAX_ACKED_DRAFT_IDS:
                            del self._acked_draft_client_ids[
                                : len(self._acked_draft_client_ids) - _MAX_ACKED_DRAFT_IDS
                            ]
                else:
                    remaining.append(draft)
            self._pending_drafts = remaining
            if removed:
                self._write_state_locked()
            return removed


_DRAFT_TEMPLATES: dict[str, dict[str, str]] = {
    # §十五: every supported workspace language gets a natural draft, not a
    # zh/en binary. Unknown languages fall back to English.
    "zh-CN": {
        "intro": "请帮我理解这段内容（来自《{source}》）：",
        "source_line": "来源：{url}",
        "ask": "请结合这段内容解释关键概念，并告诉我下一步该练什么。",
        "fallback_source": "选中的内容",
        "pdf_source": "PDF 文档",
        "github_source": "GitHub 仓库",
    },
    "en-US": {
        "intro": "Help me understand this excerpt (from \u201c{source}\u201d):",
        "source_line": "Source: {url}",
        "ask": "Explain the key ideas here and suggest what I should practise next.",
        "fallback_source": "the captured page",
        "pdf_source": "PDF document",
        "github_source": "GitHub repository",
    },
    "es-ES": {
        "intro": "Ayudame a entender este fragmento (de \u00ab{source}\u00bb):",
        "source_line": "Fuente: {url}",
        "ask": "Explica las ideas clave y sugiere que deberia practicar a continuacion.",
        "fallback_source": "la pagina capturada",
        "pdf_source": "documento PDF",
        "github_source": "repositorio de GitHub",
    },
    "fr-FR": {
        "intro": "Aide-moi a comprendre cet extrait (de \u00ab {source} \u00bb) :",
        "source_line": "Source : {url}",
        "ask": "Explique les idees cles et suggere ce que je devrais pratiquer ensuite.",
        "fallback_source": "la page capturee",
        "pdf_source": "document PDF",
        "github_source": "dépôt GitHub",
    },
    "de-DE": {
        "intro": "Hilf mir, diesen Ausschnitt zu verstehen (aus \u201e{source}\u201c):",
        "source_line": "Quelle: {url}",
        "ask": "Erklare die Kernideen und schlage vor, was ich als Nachstes uben sollte.",
        "fallback_source": "die erfasste Seite",
        "pdf_source": "PDF-Dokument",
        "github_source": "GitHub-Repository",
    },
    "ja-JP": {
        "intro": "この抜粋を理解したいです（出典：{source}）：",
        "source_line": "出典：{url}",
        "ask": "重要な考え方を説明し、次に何を練習すべきか教えてください。",
        "fallback_source": "取り込んだページ",
        "pdf_source": "PDF ドキュメント",
        "github_source": "GitHub リポジトリ",
    },
    "ko-KR": {
        "intro": "이 발췌를 이해하고 싶어요(출처: {source}):",
        "source_line": "출처: {url}",
        "ask": "핵심 개념을 설명하고 다음에 무엇을 연습해야 할지 알려 주세요.",
        "fallback_source": "캡처한 페이지",
        "pdf_source": "PDF 문서",
        "github_source": "GitHub 리포지토리",
    },
    "pt-BR": {
        "intro": "Ajude-me a entender este trecho (de \u201c{source}\u201d):",
        "source_line": "Fonte: {url}",
        "ask": "Explique as ideias principais e sugira o que devo praticar em seguida.",
        "fallback_source": "a pagina capturada",
        "pdf_source": "documento PDF",
        "github_source": "repositório do GitHub",
    },
}


def _draft_template(language: str | None) -> dict[str, str]:
    normalized = str(language or "").strip()
    if normalized in _DRAFT_TEMPLATES:
        return _DRAFT_TEMPLATES[normalized]
    prefix = normalized.split("-", 1)[0].lower()
    if prefix:
        for key, template in _DRAFT_TEMPLATES.items():
            if key.split("-", 1)[0].lower() == prefix:
                return template
    return _DRAFT_TEMPLATES["en-US"]


def build_coach_draft_text(
    *,
    selection: str,
    url: str = "",
    title: str = "",
    language: str | None = None,
    question: str = "",
    source_kind: str = "",
) -> str:
    """Compose the pre-filled, editable coach draft for one selection.

    The shape is deliberately plain text (the Coach composer is the editor):
    an intent line, the quoted excerpt, then the source line. ``language``
    follows the workspace's effective response language — all eight supported
    languages have a template; unknown languages fall back to English.

    A learner question from the browser Ask Trainer entry replaces the
    default ask line with the learner's own words — the question is the ask.
    """

    template = _draft_template(language)
    source_label = title
    if not source_label:
        # P4: a PDF document or GitHub repo page without a title names its
        # kind (not a bare URL), so the coach knows what it is looking at.
        kind_key = {"pdf": "pdf_source", "github_repo": "github_source"}.get(
            str(source_kind or "").strip().lower()
        )
        source_label = (template.get(kind_key) if kind_key else None) or url or template["fallback_source"]
    ask_line = str(question or "").strip() or template["ask"]
    quote = "\n".join(f"> {line}" if line else ">" for line in selection.splitlines())
    lines = [template["intro"].format(source=source_label), "", quote, ""] if quote else []
    if not quote:
        return f"{source_label}\n{template['source_line'].format(url=url)}"
    if url:
        lines.append(template["source_line"].format(url=url))
    lines.append("")
    lines.append(ask_line)
    return "\n".join(lines)


__all__ = [
    "BrowserBridgeService",
    "BrowserCredential",
    "BrowserPairingError",
    "PairCodeRegistration",
    "build_coach_draft_text",
]
