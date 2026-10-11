"""Bibliography rules for Submission Preflight.

Collects every citation key used across the whole source (``collect_cite_keys``) and checks it
against the manuscript's ``.bib`` content (``check_bibliography``): a cite with no matching entry,
a BibTeX entry missing a field its type requires, an entry with no DOI and no arXiv ``eprint``, two
entries that are really the same work, and an entry nobody cites.

Suppression on ``unresolved_includes`` is the runner's job, not this module's: see
``rules-dispatch-context.md``. This rule emits findings unconditionally.
"""

from __future__ import annotations

import re

from src.services.citations.title_match import normalize_title
from src.services.parser.latex import CITE_RE, extract_cite_keys, parse_bib_entries
from src.services.preflight.catalogue import Finding
from src.services.preflight.source import PreflightSource

# Capitalized natbib forms (\Cite, \Citep, \Citet, \Citeauthor, \Citeyear) with their optional
# notes and star. CITE_RE's literal "cite" is lowercase, so it cannot match these (spec §4.4) —
# longest names are listed first so the alternation can't stop one prefix short.
_CAPITALIZED_NATBIB_CITE_RE = re.compile(
    r"\\(?:Citeauthor|Citeyear|Citep|Citet|Cite)\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]+)\}"
)

# Required fields beyond "title", by lowercased @type. A type not listed here (e.g. @misc, @online)
# only requires "title".
_REQUIRED_FIELDS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "article": ("journal", "year"),
    "inproceedings": ("booktitle", "year"),
    "conference": ("booktitle", "year"),
    "book": ("publisher", "year"),
    "phdthesis": ("school", "year"),
    "mastersthesis": ("school", "year"),
}


def _required_fields(entry_type: str) -> tuple[str, ...]:
    return ("title", *_REQUIRED_FIELDS_BY_TYPE.get(entry_type, ()))


def collect_cite_keys(src: PreflightSource) -> dict[str, tuple[str, int]]:
    """Map every cited key to its first citing (file, 1-based line), main file before includes.

    The key set is the union of ``extract_cite_keys`` — the repo's own \\cite/natbib/biblatex
    regex, reused rather than reimplemented, which already excludes ``\\nocite`` and friends — and
    the capitalized natbib forms it cannot match. Positions are then located by scanning the same
    two patterns (``CITE_RE`` itself, not a copy of it) and keeping only matches for keys already
    confirmed real by the set above, so a stray ``\\nocite`` can't donate a bogus position for a
    key it doesn't actually cite.
    """
    result: dict[str, tuple[str, int]] = {}
    for path, masked in src.iter_masked():
        valid_keys = set(extract_cite_keys(masked))
        for match in _CAPITALIZED_NATBIB_CITE_RE.finditer(masked):
            valid_keys.update(key.strip() for key in match.group(1).split(",") if key.strip())
        if not valid_keys:
            continue

        occurrences: list[tuple[int, str]] = []
        for match in CITE_RE.finditer(masked):
            for raw_key in match.group(2).split(","):
                key = raw_key.strip()
                if key in valid_keys:
                    occurrences.append((match.start(), key))
        for match in _CAPITALIZED_NATBIB_CITE_RE.finditer(masked):
            for raw_key in match.group(1).split(","):
                key = raw_key.strip()
                if key in valid_keys:
                    occurrences.append((match.start(), key))

        for offset, key in sorted(occurrences):
            if key not in result:
                result[key] = (path, src.locate(path, offset))
    return result


def check_bibliography(src: PreflightSource, bib_content: str) -> list[Finding]:
    """Cite-key and BibTeX-entry hygiene.

    An empty ``parse_bib_entries`` result means no bibliography was supplied at all, which must
    report nothing rather than flag every citation as missing — a paper whose ``.bib`` was simply
    not sent must not look catastrophically broken.
    """
    entries = parse_bib_entries(bib_content)
    if not entries:
        return []

    cited = collect_cite_keys(src)
    findings: list[Finding] = []

    # bib.cite_key_missing — a \cite key with no entry anywhere in the bibliography.
    for key, (path, line) in cited.items():
        if key not in entries:
            findings.append(Finding(rule="bib.cite_key_missing", file=path, line=line, symbol=key))

    # bib.missing_required_field / bib.missing_doi — per entry; findings carry no file/line since
    # the bibliography isn't one of src's files.
    for key, entry in entries.items():
        for field in _required_fields(entry.get("type", "")):
            if not entry.get(field, "").strip():
                findings.append(Finding(rule="bib.missing_required_field", symbol=field, excerpt=key))
        if not entry.get("doi", "").strip() and not entry.get("eprint", "").strip():
            findings.append(Finding(rule="bib.missing_doi", symbol=key))

    # bib.duplicate_entry — group by lowercased, stripped DOI when present (DOIs are case-
    # insensitive), else by normalized title. One finding per duplicate GROUP, not per entry.
    groups: dict[str, list[str]] = {}
    for key, entry in entries.items():
        doi = entry.get("doi", "").strip().lower()
        group_key = doi or normalize_title(entry.get("title", ""))
        if not group_key:
            continue
        groups.setdefault(group_key, []).append(key)
    for group_key, keys in groups.items():
        if len(keys) > 1:
            findings.append(Finding(rule="bib.duplicate_entry", symbol=group_key, count=len(keys)))

    # bib.uncited_entry — emitted unconditionally; suppression on unresolved_includes is the
    # runner's job (see rules-dispatch-context.md), not this module's.
    for key in entries:
        if key not in cited:
            findings.append(Finding(rule="bib.uncited_entry", symbol=key))

    return findings
