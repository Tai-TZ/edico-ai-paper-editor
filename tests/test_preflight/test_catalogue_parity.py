"""Cross-language parity: the frontend's rule-id union must mirror the backend catalogue exactly.

This is the one place a cross-language file read is justified. Everywhere else, `Record<PreflightRuleId,
...>` inside `Record<UiLanguage, PreflightCopy>` already makes a missing translation a
`npm run typecheck` failure (frontend/src/lib/preflight-i18n.ts) — the type system cannot, however,
catch the backend catalogue growing a rule id the frontend has never heard of, nor the reverse (a
frontend id the backend dropped or never had). Reading `preflight-api.ts` as text and comparing the
exact set of rule-id string literals to `PREFLIGHT_RULE_IDS` catches both directions.
"""

from __future__ import annotations

import pathlib
import re

from src.services.preflight.catalogue import PREFLIGHT_RULE_IDS

_TS = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/lib/api/preflight-api.ts"


def test_the_typescript_union_matches_the_python_catalogue():
    text = _TS.read_text(encoding="utf-8")
    union = set(re.findall(r'"((?:crossref|bib|statement|format|anon|length)\.[a-z_]+)"', text))
    assert union == set(PREFLIGHT_RULE_IDS)


def test_the_typescript_union_has_no_duplicate_literals():
    # set(re.findall(...)) above would silently absorb a duplicate id typed twice in the TS union
    # (e.g. a copy-paste of "crossref.undefined_ref" in place of a missing "crossref.unused_label")
    # as long as the *set* of distinct ids still matched — the count would not. Comparing the raw
    # match count to the set size catches that even though the set-equality test above would not.
    text = _TS.read_text(encoding="utf-8")
    matches = re.findall(r'"((?:crossref|bib|statement|format|anon|length)\.[a-z_]+)"', text)
    assert len(matches) == len(set(matches))
