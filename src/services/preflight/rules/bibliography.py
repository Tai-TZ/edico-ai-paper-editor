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

# Fields required above that parse_bib_entries' dict never carries (it only returns key, type,
# title, author, year, doi, eprint, journal, raw — see src/services/parser/latex.py). Checked
# instead by a brace-depth-aware scan of the entry's raw text for a field that begins at the
# entry's own top level — never inside the value of some other field, which is the only place a
# real BibTeX field can start. See `_raw_top_level_fields` for the scan and `_field_is_present`
# for how its result is used, including the fallback for an entry whose braces don't balance.
_RAW_ONLY_FIELDS = frozenset({"publisher", "booktitle", "school"})

# "name = value" for one top-level, comma-delimited segment of an entry's raw text (see
# `_raw_top_level_fields`); the caller lowercases the captured name since BibTeX field names are
# case-insensitive.
_TOP_LEVEL_FIELD_RE = re.compile(r"^\s*([A-Za-z][\w-]*)\s*=\s*(.*)$", re.DOTALL)

# Last-resort presence scan for a raw-only field, used only when `_raw_top_level_fields` reports
# the entry's braces as unbalanced and so cannot be trusted to have found every top-level field.
# Unanchored on purpose — matching the field's name anywhere ahead of "=" risks a false "present"
# (the exact bug this module had to fix for well-formed entries), but on malformed input a missed
# "present" (a false "missing" finding) is the worse failure, per the project's rule that a false
# positive is more damaging than a false negative.
_RAW_ONLY_FIELD_FALLBACK_RE: dict[str, re.Pattern[str]] = {
    field: re.compile(
        r"\b" + field + r"\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,}\s][^,}]*)",
        re.IGNORECASE,
    )
    for field in _RAW_ONLY_FIELDS
}


def _required_fields(entry_type: str) -> tuple[str, ...]:
    return ("title", *_REQUIRED_FIELDS_BY_TYPE.get(entry_type, ()))


def _strip_braces_or_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == "{" and value[-1] == "}":
        return value[1:-1].strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].strip()
    return value


def _raw_top_level_fields(raw: str) -> tuple[dict[str, str], bool]:
    """Fields that start at brace depth 0 in an entry's raw text, plus whether braces balanced.

    ``raw`` (from ``parse_bib_entries``) is the entry body after ``key,`` *including* the
    entry's own closing delimiter, so a well-formed entry's text is exactly one closing
    brace/paren short of balanced; that trailing delimiter is dropped before depth is tracked.
    A field only begins at depth 0 — inside any ``{...}`` nesting it is just text, however much
    it looks like ``name =`` (so ``title={On school = society}`` never gives "school" a
    top-level entry, and ``title={a, school = b}`` never lets that inner comma split a field).
    Top-level (depth-0) commas are what separate one field from the next.

    This does not track quotes, so a stray unmatched brace inside a quoted value can throw the
    depth count off for the rest of the entry — callers must not treat an "absent" result as
    trustworthy when the returned ``balanced`` flag is ``False``.
    """
    body = raw[:-1] if raw.endswith(("}", ")")) else raw
    fields: dict[str, str] = {}
    depth = 0
    balanced = True
    start = 0
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                balanced = False
                depth = 0
        elif ch == "," and depth == 0:
            _record_top_level_field(body[start:i], fields)
            start = i + 1
    _record_top_level_field(body[start:], fields)
    return fields, balanced and depth == 0


def _record_top_level_field(segment: str, fields: dict[str, str]) -> None:
    match = _TOP_LEVEL_FIELD_RE.match(segment)
    if match:
        fields[match.group(1).lower()] = match.group(2)


def _field_is_present(entry: dict, field: str) -> bool:
    """Non-empty value for ``field`` on a parsed bib entry.

    Prefers the parsed dict (title, author, year, doi, eprint, journal — the fields
    parse_bib_entries actually exposes). For the three it does not (publisher, booktitle,
    school), looks the field up among the entry's top-level fields first; only when the raw
    text's braces don't balance — so that lookup can't be trusted to be complete — does it fall
    back to the unanchored presence regex.
    """
    if field in _RAW_ONLY_FIELDS:
        raw = entry.get("raw", "")
        top_level, balanced = _raw_top_level_fields(raw)
        if field in top_level:
            return bool(_strip_braces_or_quotes(top_level[field]))
        if not balanced:
            match = _RAW_ONLY_FIELD_FALLBACK_RE[field].search(raw)
            return bool(match and _strip_braces_or_quotes(match.group(1)))
        return False
    return bool(entry.get(field, "").strip())


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
            if not _field_is_present(entry, field):
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
