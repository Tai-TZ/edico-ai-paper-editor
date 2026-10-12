"""Rule catalogue for Submission Preflight.

The single source of truth for rule ids, their groups, and their severities. No Pydantic here:
this module stays pure (plain tuples, a plain mapping, a plain frozen dataclass) so the six rule
modules under ``src/services/preflight/rules/`` and the runner can import it without pulling in
the schema layer. The Pydantic request/response models live in ``src/models/preflight_schemas.py``
and import ``PREFLIGHT_GROUPS``/``RULE_SEVERITY`` from here, not the other way around.

A rule module reports what it found (a ``Finding``); the catalogue decides how bad it is
(``RULE_SEVERITY``). Keeping severity out of ``Finding`` is deliberate — it is the runner's job,
not the rule's, to look up the severity for a rule id.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

PREFLIGHT_GROUPS: tuple[str, ...] = ("crossref", "bib", "statement", "format", "anon", "length")

# All 29 rule ids from the design spec (section 3), in group order. This is the one place the
# full catalogue is enumerated; the runner, the rule modules, and the frontend's mirrored
# TypeScript union all trace back to this tuple.
PREFLIGHT_RULE_IDS: tuple[str, ...] = (
    # crossref.* (3.1) — always runs
    "crossref.undefined_ref",
    "crossref.float_without_label",
    "crossref.unused_label",
    "crossref.duplicate_label",
    # bib.* (3.2) — always runs
    "bib.cite_key_missing",
    "bib.duplicate_entry",
    "bib.missing_required_field",
    "bib.missing_doi",
    "bib.uncited_entry",
    # statement.* (3.3) — always runs, each item independently toggleable via profile
    "statement.data_availability_missing",
    "statement.ethics_missing",
    "statement.coi_missing",
    "statement.funding_missing",
    "statement.author_contributions_missing",
    # format.* (3.4) — always runs
    "format.compressed_leading",
    "format.margin_override",
    "format.large_negative_vspace",
    "format.font_size_override",
    # anon.* (3.5) — only when profile.double_blind is True
    "anon.author_populated",
    "anon.affiliation_populated",
    "anon.email_present",
    "anon.orcid_present",
    "anon.thanks_present",
    "anon.acknowledgements_present",
    "anon.funding_identifiers",
    "anon.self_reference",
    "anon.repository_link",
    # length.* (3.6) — only when profile.word_limit is set
    "length.over_limit",
    "length.near_limit",
)

# rule id -> "critical" | "warning" | "info". `critical` is reserved for rules that are certain
# to be wrong and certain to have consequences (see spec 3, intro); every heuristic rule is
# `warning` or `info`. This set of 7 critical rules is pinned by
# tests/test_preflight/test_catalogue.py::test_only_the_spec_s_rules_are_critical.
#
# `length.over_limit` is `warning`, not the `critical` spec 3.6's table first listed: the word
# count is an approximation of what a venue will measure (3.6's own prose calls it "xap xi, chi
# dung de canh bao som"), and spec 3's governing principle is that a heuristic cannot be
# `critical`. A critical row that renders "this count is only an estimate" underneath it is
# self-contradicting copy. The spec table was corrected to match (final whole-branch review,
# ruling 29).
RULE_SEVERITY: Mapping[str, str] = {
    "crossref.undefined_ref": "critical",
    "crossref.float_without_label": "warning",
    "crossref.unused_label": "info",
    "crossref.duplicate_label": "critical",
    "bib.cite_key_missing": "critical",
    "bib.duplicate_entry": "warning",
    "bib.missing_required_field": "warning",
    "bib.missing_doi": "info",
    "bib.uncited_entry": "info",
    "statement.data_availability_missing": "warning",
    "statement.ethics_missing": "warning",
    "statement.coi_missing": "warning",
    "statement.funding_missing": "warning",
    "statement.author_contributions_missing": "info",
    "format.compressed_leading": "critical",
    "format.margin_override": "warning",
    "format.large_negative_vspace": "warning",
    "format.font_size_override": "warning",
    "anon.author_populated": "critical",
    "anon.affiliation_populated": "critical",
    "anon.email_present": "critical",
    "anon.orcid_present": "warning",
    "anon.thanks_present": "warning",
    "anon.acknowledgements_present": "warning",
    "anon.funding_identifiers": "warning",
    "anon.self_reference": "info",
    "anon.repository_link": "info",
    "length.over_limit": "warning",
    "length.near_limit": "info",
}


@dataclass(frozen=True)
class Finding:
    """What every rule module returns.

    Deliberately carries no ``severity``: the runner looks that up in ``RULE_SEVERITY`` by
    ``rule`` when it converts this to the Pydantic ``PreflightFinding``. A rule reports what it
    found; the catalogue decides how bad it is.
    """

    rule: str
    file: str = ""
    line: int | None = None
    symbol: str = ""
    count: int = 1
    excerpt: str = ""
