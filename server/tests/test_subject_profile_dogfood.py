"""P2 #26: Japanese-learning / German-grammar / French-writing dogfood profiles.

The three language-learning subjects ship as pure JSON in ``profiles/`` — zero
code changes. These tests verify the data lands, passes the same fail-closed
validation as the built-ins, resolves through the verifier registry, and never
hijacks the canonical ``code`` / ``literature`` family keys.
"""

from __future__ import annotations

import pytest

from app.evaluator.hooks import SUPPORTED_HOOK_LOCALES
from app.evaluator.verifiers import VERIFIER_REGISTRY
from app.training.subject_profile import get_subject_profile, load_subject_profiles
from app.training.subject_taxonomy import verifier_subject_family

DOGFLOOD_IDS = ("japanese-learning", "german-grammar", "french-writing")

_LABEL_LANGUAGES = {
    "zh-CN",
    "en-US",
    "es-ES",
    "fr-FR",
    "de-DE",
    "ja-JP",
    "ko-KR",
    "pt-BR",
}


def test_dogfood_profiles_load_and_pass_fail_closed_validation() -> None:
    profiles = load_subject_profiles()
    for profile_id in DOGFLOOD_IDS:
        profile = profiles[profile_id]
        assert profile.verifier_pack in VERIFIER_REGISTRY
        assert len(profile.dimensions) == len(set(profile.dimensions)) > 0
        assert set(profile.deliverable_kinds) <= {"file_based", "text_payload"}
        assert profile.family == "language-learning"


def test_dogfood_profiles_do_not_hijack_canonical_family_keys() -> None:
    profiles = load_subject_profiles()
    # The canonical families must still resolve to their own profiles even
    # though the language-learning profiles share the verifier pack.
    assert profiles["code"].id == "code"
    assert profiles["literature"].id == "literature"
    for profile_id in DOGFLOOD_IDS:
        resolved = get_subject_profile(profile_id)
        assert resolved.id == profile_id
        assert resolved.family == "language-learning"


def test_dogfood_profiles_resolve_to_the_literature_verifier_pack() -> None:
    for profile_id in DOGFLOOD_IDS:
        assert verifier_subject_family(profile_id) == "literature"
    # Canonical families keep their historical resolution.
    assert verifier_subject_family("code") == "code"
    assert verifier_subject_family("literature") == "literature"
    assert verifier_subject_family("unknown-subject") == "code"


@pytest.mark.parametrize("profile_id", DOGFLOOD_IDS)
def test_dogfood_profile_locale_adaptation_and_labels(profile_id: str) -> None:
    profile = get_subject_profile(profile_id)
    default_locale = profile.locale_adaptation.get("default_content_locale")
    assert default_locale in SUPPORTED_HOOK_LOCALES
    assert profile.dimension_labels.keys() >= _LABEL_LANGUAGES
    for labels in profile.dimension_labels.values():
        assert set(labels.keys()) == set(profile.dimensions)
        assert all(str(value).strip() for value in labels.values())


def test_japanese_learning_is_cjk_counted_and_german_french_are_latin_counted() -> None:
    japanese = get_subject_profile("japanese-learning")
    assert japanese.locale_adaptation.get("counter_mode") == "cjk_char_or_latin_word"
    for profile_id in ("german-grammar", "french-writing"):
        profile = get_subject_profile(profile_id)
        assert profile.locale_adaptation.get("counter_mode") == "latin_word"
