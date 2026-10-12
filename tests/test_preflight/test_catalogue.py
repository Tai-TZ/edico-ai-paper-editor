"""Rule catalogue and request/response schema tests for Submission Preflight."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.preflight_schemas import PreflightProfile, PreflightRequest
from src.services.preflight.catalogue import PREFLIGHT_GROUPS, PREFLIGHT_RULE_IDS, RULE_SEVERITY


def test_every_rule_id_is_group_qualified_and_unique():
    assert len(set(PREFLIGHT_RULE_IDS)) == len(PREFLIGHT_RULE_IDS)
    for rule in PREFLIGHT_RULE_IDS:
        group, _, name = rule.partition(".")
        assert group in PREFLIGHT_GROUPS, rule
        assert name, rule


def test_every_rule_has_a_severity():
    assert set(RULE_SEVERITY) == set(PREFLIGHT_RULE_IDS)
    assert set(RULE_SEVERITY.values()) <= {"critical", "warning", "info"}


def test_only_the_spec_s_rules_are_critical():
    critical = {r for r, s in RULE_SEVERITY.items() if s == "critical"}
    assert critical == {
        "crossref.undefined_ref",
        "crossref.duplicate_label",
        "bib.cite_key_missing",
        "format.compressed_leading",
        "anon.author_populated",
        "anon.affiliation_populated",
        "anon.email_present",
    }
    # length.over_limit is deliberately NOT here: the word count is an estimate (spec 3.6's own
    # prose), and spec 3's governing principle bars a heuristic from `critical`. Demoted in the
    # final whole-branch review, ruling 29.
    assert RULE_SEVERITY["length.over_limit"] == "warning"


def test_profile_defaults_match_the_spec():
    p = PreflightProfile()
    assert p.double_blind is False and p.word_limit is None
    assert p.required_statements == ["data_availability", "ethics", "coi", "funding"]


def test_request_rejects_an_unsafe_main_file():
    with pytest.raises(ValidationError):
        PreflightRequest(main_file="../etc/passwd")
