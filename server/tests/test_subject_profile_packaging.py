"""The subject profiles ship with the sidecar in every layout.

They used to live at the repository root and were looked up relative to the
source tree. A packaged Trainer — the bundled ``server/app`` tree or the
frozen binary — therefore loaded none: every language-learning subject
silently fell back to the code profile. These tests pin the profiles as
package data, which is what makes them travel.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.training import subject_profile
from app.training.subject_profile import (
    builtin_profiles_dir,
    get_subject_profile,
    load_subject_profiles,
)
from app.training.subject_taxonomy import verifier_subject_family

SHIPPED_SUBJECTS = {
    "code",
    "literature",
    "french-writing",
    "german-grammar",
    "japanese-learning",
}
LANGUAGE_SUBJECTS = {"french-writing", "german-grammar", "japanese-learning"}

# Captured at import, before any test redirects the module path: where the
# shipped files really are in this checkout.
TRAINING_PACKAGE_DIR = Path(subject_profile.__file__).resolve().parent


def shipped(name: str) -> Path:
    return TRAINING_PACKAGE_DIR / "profiles" / f"{name}.profile.json"


def test_builtin_profiles_are_package_data() -> None:
    profiles_dir = TRAINING_PACKAGE_DIR / "profiles"
    # Looked up next to the module, not from where the checkout happens to be.
    assert builtin_profiles_dir() == profiles_dir
    assert {
        path.name.removesuffix(".profile.json") for path in profiles_dir.glob("*.profile.json")
    } == SHIPPED_SUBJECTS


def test_profiles_load_from_a_copied_package_with_no_repository_around_it(tmp_path: Path) -> None:
    # This is the bundled layout of a VSIX: the package, and nothing else.
    package = tmp_path / "server" / "app" / "training"
    shutil.copytree(
        TRAINING_PACKAGE_DIR,
        package,
        ignore=shutil.ignore_patterns("__pycache__", "._*"),
    )

    loaded = load_subject_profiles(package / "profiles")

    assert SHIPPED_SUBJECTS <= set(loaded)
    for subject in LANGUAGE_SUBJECTS:
        assert loaded[subject].family == "language-learning"
    # None of them is the code profile under another name: writing is
    # delivered as text, not as the code profile's artifacts.
    assert loaded["code"].deliverable_kinds != loaded["japanese-learning"].deliverable_kinds
    # And each language is its own profile, with its own labelled dimensions.
    language_profiles = [loaded[subject] for subject in sorted(LANGUAGE_SUBJECTS)]
    assert all(
        left != right
        for index, left in enumerate(language_profiles)
        for right in language_profiles[index + 1 :]
    )
    assert len({str(loaded[subject].dimension_labels) for subject in LANGUAGE_SUBJECTS}) == len(
        LANGUAGE_SUBJECTS
    )


def test_a_language_subject_resolves_to_its_own_profile_and_family() -> None:
    for subject in sorted(SHIPPED_SUBJECTS):
        assert get_subject_profile(subject).id == subject
    for subject in LANGUAGE_SUBJECTS:
        # Language subjects are verified as writing, not as code.
        assert verifier_subject_family(subject) == "literature"
    assert verifier_subject_family("code") == "code"
    assert verifier_subject_family("literature") == "literature"


def test_builtin_registry_is_cached_until_a_profile_file_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Stand in for a packaged module: the lookup only uses the module path.
    monkeypatch.setattr(
        subject_profile,
        "__file__",
        str(tmp_path / "app" / "training" / "subject_profile.py"),
    )
    monkeypatch.setattr(subject_profile, "_BUILTIN_REGISTRY", None)
    profiles = tmp_path / "app" / "training" / "profiles"
    profiles.mkdir(parents=True)
    probe = profiles / "code.profile.json"
    shutil.copy(shipped("code"), probe)

    reads: list[str] = []
    real_loads = subject_profile.json.loads

    def counting_loads(text: str, *args: object, **kwargs: object) -> object:
        reads.append(text)
        return real_loads(text, *args, **kwargs)

    monkeypatch.setattr(subject_profile.json, "loads", counting_loads)

    first = load_subject_profiles()
    assert set(first) == {"code"}
    assert len(reads) == 1
    # An unchanged file is not read again: the next lookup is served from memory.
    assert load_subject_profiles() == first
    assert len(reads) == 1
    # The cache never hands out the registry itself.
    load_subject_profiles()["extra"] = first["code"]
    assert "extra" not in load_subject_profiles()

    # A changed file is read again, so an edited profile is not hidden by the cache.
    shutil.copy(shipped("literature"), probe)
    reloaded = load_subject_profiles()
    assert len(reads) == 2
    assert "literature" in reloaded
    assert reloaded != first


def test_legacy_repository_root_profiles_are_still_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # An older checkout kept the files at the repository root; it must not break.
    repo_root = tmp_path / "repo"
    monkeypatch.setattr(
        subject_profile,
        "__file__",
        str(repo_root / "server" / "app" / "training" / "subject_profile.py"),
    )
    legacy = repo_root / "profiles"
    legacy.mkdir(parents=True)
    shutil.copy(shipped("code"), legacy / "code.profile.json")

    assert builtin_profiles_dir() == legacy
    assert "code" in load_subject_profiles(legacy)
