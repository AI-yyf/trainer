"""SubjectProfile data registry (§2.5 P1-P5 of the general-coach pivot design).

Principles enforced here:
- P1: Profile is data, not code. Adding a new subject = adding one ``*.profile.json``
  file in ``profiles/`` that passes ``validate_subject_profile``.
- P2: 3D orthogonality (UI language × content language × learner language).
- P3: Locale-aware deterministic hooks (zh/en/ja/de/fr/ko/es/pt).
- P4: Governance semantics are globally uniform — the 5-state projection ladder,
  dual-context transfer rule, trusted verification source whitelist, and
  evidence invalidation rules cannot be modified by any profile.
- P5: Zero-code third/fourth subject gate (e.g. Japanese learning, German grammar,
  French writing live purely as JSON files in ``profiles/``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..evaluator.hooks import SUPPORTED_HOOK_LOCALES, normalize_hook_locale
from ..evaluator.verifiers import VERIFIER_REGISTRY

SUBJECT_PROFILE_TYPE = "trainer.subject.profile"
SUBJECT_PROFILE_VERSION = 1
ALLOWED_DELIVERABLE_KINDS = frozenset({"file_based", "text_payload"})
FORBIDDEN_GOVERNANCE_OVERRIDE_KEYS = frozenset(
    {
        "trust_sources",
        "trusted_verification_sources",
        "state_machine",
        "skill_states",
        "allow_unanchored_rubric",
        "bypass_verification",
        "evidence_rules",
    }
)


@dataclass(frozen=True)
class SubjectProfile:
    """Validated, immutable subject profile loaded from data."""

    id: str
    family: str
    verifier_pack: str
    dimensions: tuple[str, ...]
    dimension_labels: dict[str, dict[str, str]]
    deliverable_kinds: tuple[str, ...]
    skill_triggers: tuple[str, ...] = ()
    scenario_packs: tuple[str, ...] = ()
    workspace_signatures: dict[str, Any] = field(default_factory=dict)
    locale_adaptation: dict[str, Any] = field(default_factory=dict)
    unverifiable_capabilities: tuple[str, ...] = ()
    inspect_only: bool = False


def _repo_profiles_dir() -> Path:
    # Check repo root `profiles/` first, then `server/app/training/profiles/` fallback.
    repo_root_profiles = Path(__file__).resolve().parents[3] / "profiles"
    if repo_root_profiles.is_dir():
        return repo_root_profiles
    return Path(__file__).resolve().parent / "profiles"


def validate_subject_profile(
    payload: Mapping[str, Any],
    *,
    external: bool = False,
) -> SubjectProfile:
    """Validate a raw ``subject.profile`` JSON mapping fail-closed (§2.5, §9).

    Raises ``ValueError`` on any schema or governance violation:
    - Missing/wrong ``_type`` or ``version``;
    - Attempt to override governance rules (P4);
    - Unknown ``verifier_pack`` (must be in ``VERIFIER_REGISTRY``);
    - Empty ``dimensions`` or invalid ``deliverable_kinds``;
    - Declaration of ``unbounded`` hooks or empty rubric overrides (§9 risk mitigation).
    """
    if not isinstance(payload, Mapping):
        raise ValueError("subject.profile must be a JSON object")
    profile_type = str(payload.get("_type") or "").strip()
    if profile_type != SUBJECT_PROFILE_TYPE:
        raise ValueError(
            f"unsupported subject.profile _type: expected '{SUBJECT_PROFILE_TYPE}', "
            f"got '{profile_type or '(missing)'}'"
        )
    version = payload.get("version")
    if version != SUBJECT_PROFILE_VERSION:
        raise ValueError(
            f"unsupported subject.profile version: expected {SUBJECT_PROFILE_VERSION}, got {version!r}"
        )

    forbidden_hits = FORBIDDEN_GOVERNANCE_OVERRIDE_KEYS.intersection(payload.keys())
    if forbidden_hits:
        raise ValueError(
            f"subject.profile may not override governance semantics (P4): {sorted(forbidden_hits)}"
        )

    profile_id = str(payload.get("id") or "").strip().lower()
    family = str(payload.get("family") or "").strip().lower()
    if not profile_id or not family:
        raise ValueError("subject.profile requires non-empty 'id' and 'family'")

    verifier_pack = str(payload.get("verifier_pack") or "").strip().lower()
    if verifier_pack not in VERIFIER_REGISTRY:
        raise ValueError(
            f"subject.profile '{profile_id}' references unregistered verifier_pack '{verifier_pack}'"
        )

    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, list) or not raw_dimensions:
        raise ValueError(f"subject.profile '{profile_id}' requires a non-empty 'dimensions' list")
    dimensions: list[str] = []
    for item in raw_dimensions:
        dim = str(item or "").strip()
        if not dim or dim in dimensions:
            raise ValueError(
                f"subject.profile '{profile_id}' has empty or duplicate dimension '{dim}'"
            )
        dimensions.append(dim)

    raw_deliverables = payload.get("deliverable_kinds")
    if not isinstance(raw_deliverables, list) or not raw_deliverables:
        raise ValueError(
            f"subject.profile '{profile_id}' requires a non-empty 'deliverable_kinds' list"
        )
    deliverable_kinds: list[str] = []
    for item in raw_deliverables:
        kind = str(item or "").strip()
        if kind not in ALLOWED_DELIVERABLE_KINDS:
            raise ValueError(
                f"subject.profile '{profile_id}' has unsupported deliverable_kind '{kind}'"
            )
        if kind not in deliverable_kinds:
            deliverable_kinds.append(kind)

    # Guard against unbounded hooks or empty rubric declarations (§9).
    hooks_decl = payload.get("hooks") or payload.get("deterministic_hooks")
    if isinstance(hooks_decl, Mapping) and hooks_decl.get("unbounded") is True:
        raise ValueError(f"subject.profile '{profile_id}' declares forbidden unbounded hook")
    if isinstance(hooks_decl, list) and any(
        (isinstance(h, str) and h.strip().lower() == "unbounded")
        or (isinstance(h, Mapping) and (h.get("unbounded") is True or h.get("type") == "unbounded"))
        for h in hooks_decl
    ):
        raise ValueError(f"subject.profile '{profile_id}' declares forbidden unbounded hook")

    locale_adaptation = payload.get("locale_adaptation")
    if isinstance(locale_adaptation, Mapping):
        if locale_adaptation.get("unbounded") is True:
            raise ValueError(f"subject.profile '{profile_id}' declares forbidden unbounded hook")
        default_locale = locale_adaptation.get("default_content_locale")
        if default_locale is not None:
            norm = normalize_hook_locale(str(default_locale))
            if norm not in SUPPORTED_HOOK_LOCALES:
                raise ValueError(
                    f"subject.profile '{profile_id}' has unsupported content locale '{default_locale}'"
                )
    else:
        locale_adaptation = {}

    if "rubric" in payload or "semantic_rubric" in payload:
        rubric_decl = payload.get("rubric") if "rubric" in payload else payload.get("semantic_rubric")
        if rubric_decl is None or (isinstance(rubric_decl, (list, dict)) and len(rubric_decl) == 0):
            raise ValueError(f"subject.profile '{profile_id}' declares forbidden empty rubric")

    raw_labels = payload.get("dimension_labels")
    dimension_labels: dict[str, dict[str, str]] = {}
    if isinstance(raw_labels, Mapping):
        for lang, mapping in raw_labels.items():
            if isinstance(mapping, Mapping):
                dimension_labels[str(lang)] = {
                    str(k): str(v) for k, v in mapping.items() if str(k).strip() and str(v).strip()
                }

    raw_triggers = payload.get("skill_triggers")
    skill_triggers = (
        tuple(str(t).strip() for t in raw_triggers if str(t).strip())
        if isinstance(raw_triggers, list)
        else ()
    )
    raw_scenarios = payload.get("scenario_packs")
    scenario_packs = (
        tuple(str(s).strip() for s in raw_scenarios if str(s).strip())
        if isinstance(raw_scenarios, list)
        else ()
    )
    raw_ws = payload.get("workspace_signatures")
    workspace_signatures = dict(raw_ws) if isinstance(raw_ws, Mapping) else {}

    raw_unverifiable = payload.get("unverifiable_capabilities")
    unverifiable_capabilities = (
        tuple(str(u).strip() for u in raw_unverifiable if str(u).strip())
        if isinstance(raw_unverifiable, list)
        else ()
    )

    return SubjectProfile(
        id=profile_id,
        family=family,
        verifier_pack=verifier_pack,
        dimensions=tuple(dimensions),
        dimension_labels=dimension_labels,
        deliverable_kinds=tuple(deliverable_kinds),
        skill_triggers=skill_triggers,
        scenario_packs=scenario_packs,
        workspace_signatures=workspace_signatures,
        locale_adaptation=dict(locale_adaptation),
        unverifiable_capabilities=unverifiable_capabilities,
        inspect_only=bool(external),
    )


def load_subject_profiles(directory: Path | None = None) -> dict[str, SubjectProfile]:
    """Load all ``*.profile.json`` files from ``profiles/`` into a registry dict."""
    target_dir = directory or _repo_profiles_dir()
    registry: dict[str, SubjectProfile] = {}
    if not target_dir.is_dir():
        return registry
    for path in sorted(target_dir.glob("*.profile.json")):
        if path.name.startswith("._"):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        profile = validate_subject_profile(raw, external=False)
        registry[profile.id] = profile
        if profile.family not in registry:
            registry[profile.family] = profile
    return registry


def get_subject_profile(family_or_id: str | None, *, directory: Path | None = None) -> SubjectProfile:
    """Resolve a profile by id or family; falls back fail-closed to 'code'."""
    registry = load_subject_profiles(directory)
    key = str(family_or_id or "").strip().lower()
    if key in registry:
        return registry[key]
    if "code" in registry:
        return registry["code"]
    raise LookupError("built-in 'code' subject.profile is missing")
