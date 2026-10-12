"""Preflight runner: the single entry point that ties the six rule modules together.

``run_preflight`` is the only function the API layer calls. Every rule module
(``rules/crossref.py``, ``rules/bibliography.py``, ``rules/statements.py``, ``rules/formatting.py``,
``rules/anonymity.py``, ``rules/length.py``) reports its findings unconditionally — it knows
nothing about a profile, about which groups should have run at all, or about one rule's finding
contradicting another's. All of that cross-cutting policy lives here, deliberately, so a single
place owns it instead of it being scattered (and duplicated, and drifted) across six modules:

- **Skip bookkeeping.** ``anon`` only runs when ``profile.double_blind`` is set; ``length`` only
  runs when ``profile.word_limit`` is set. A group that did not run goes in ``report.skipped`` —
  never silently treated as "ran clean".
- **Suppression.** Two independent conflicts, each recorded by rule id in ``report.suppressed``
  so the panel can explain itself rather than just going quiet:
  - ``src.unresolved_includes`` non-empty: a ``\\input``-ed file is missing, so every label and
    citation in it is invisible to the rules that see the whole source. ``crossref.undefined_ref``
    and ``bib.uncited_entry`` are dropped.
  - ``src.unexamined_files`` non-empty: same consequence from the opposite cause — a ``.tex`` file
    the payload *did* supply was never reached by the include graph (``\\subfile``, ``\\import``,
    ``\\InputIfFileExists``, a conditional or macro-wrapped include, or a stray unused file), so
    its labels and citations went unread. The same two rules are dropped, for the same reason, and
    recorded in ``report.suppressed`` the same way; the two causes are kept in separate report
    fields so the panel can word them differently.
  - ``profile.double_blind`` is true: a venue wants a funding / author-contributions statement in
    the camera-ready, not the blinded submission, so demanding it here while also flagging
    acknowledgements as an identity leak would be contradictory advice. ``statement.funding_missing``
    and ``statement.author_contributions_missing`` are dropped.
- **Severity.** ``Finding`` carries none; it is looked up per rule id in ``RULE_SEVERITY`` here.
- **Ids.** ``f"{rule}:{n}"`` with ``n`` a per-rule ordinal, assigned in emission order, after
  suppression and the line-bounds filter below (so ids are dense and stable for what is actually
  returned).
- **Ordering.** Critical findings first, then warning, then info, via a stable sort so that each
  group's internal relative order survives within a severity band.
- **Counts.** ``report.counts`` is severity -> number of surviving findings.
- **Line bounds.** A finding whose ``line`` is past its file's real line count is dropped outright
  (the frontend's scroll helper does not clamp past end-of-file, so a bad line would scroll to the
  bottom and highlight nothing). ``line is None`` is legitimate — ``check_statements`` and
  ``check_length`` both emit it for findings with no single meaningful location — and always
  passes through untouched. As of fix round 1, this filter is provably unreachable through all
  six rule modules as they stand today (every located finding's ``line`` comes from
  ``src.locate(path, offset)`` on a real offset into that same file's own text, which can never
  exceed that file's own real line count) — it is pure insurance against a future rule module
  computing a line number wrong, not something any current input can exercise end-to-end.

Fix round 1 added one more cross-cutting policy, the **no-content path**: when ``request.files``
is empty, ``main_file`` is absent from it, or every resolved file is blank or comment-only once
masked, there is nothing to analyse at all. That is different from a group being merely
undeclared (``skipped``) — it means no rule group actually examined any content — so it gets its
own field, ``report.no_content``, and short-circuits everything else: no findings, every group in
``skipped``, and ``suppressed`` left empty (a group that never ran cannot also have had a rule
suppressed out of it — that would tell the panel two contradictory things about the same group).
``unresolved_includes`` is still populated when that is *why* there was nothing (an empty
``files`` list or a missing ``main_file``), since it becomes the only explanation the panel has
for an entirely empty report. ``unexamined_files`` rides along on the same reasoning: when
``main_file`` is absent from a non-empty payload, every ``.tex`` the caller did send went unread,
and saying so is the only honest account of that report.
"""

from __future__ import annotations

from src.models.preflight_schemas import PreflightFinding, PreflightReport, PreflightRequest
from src.services.preflight.catalogue import PREFLIGHT_GROUPS, RULE_SEVERITY, Finding
from src.services.preflight.rules.anonymity import check_anonymity
from src.services.preflight.rules.bibliography import check_bibliography
from src.services.preflight.rules.crossref import check_crossref
from src.services.preflight.rules.formatting import check_formatting
from src.services.preflight.rules.length import check_length
from src.services.preflight.rules.statements import check_statements
from src.services.preflight.source import PreflightSource, build_source

# Severity sort key — critical first, then warning, then info.
_SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")

# Suppressed when part of the project went unread -- either a \\input target is missing from the
# payload, or a payload .tex file was never reached by the include graph. Both are the same
# conflict with spec §3.1/§3.2: see the module docstring's "Suppression" bullets.
_CROSS_FILE_SUPPRESSED_RULES: tuple[str, ...] = ("crossref.undefined_ref", "bib.uncited_entry")

# Suppressed under double-blind review (spec §3.5's conflict with §3.3).
_DOUBLE_BLIND_SUPPRESSED_RULES: tuple[str, ...] = (
    "statement.funding_missing",
    "statement.author_contributions_missing",
)

# rule id -> the `required_statements` entry it corresponds to. Fix round 1, ruling D: the
# double-blind suppression above is only recorded for a rule whose statement the profile actually
# required -- recording `statement.funding_missing` as suppressed when `required_statements` never
# asked for a funding statement would be a small lie the panel has to render.
_DOUBLE_BLIND_RULE_TO_STATEMENT: dict[str, str] = {
    "statement.funding_missing": "funding",
    "statement.author_contributions_missing": "author_contributions",
}


def _no_content_report(src: PreflightSource) -> PreflightReport:
    """The fix-round-1 no-content path: nothing to analyse, so nothing ran and nothing is suppressed."""
    return PreflightReport(
        findings=[],
        counts={severity: 0 for severity in _SEVERITY_ORDER},
        skipped=list(PREFLIGHT_GROUPS),
        suppressed=[],
        unresolved_includes=list(src.unresolved_includes),
        unexamined_files=list(src.unexamined_files),
        no_content=True,
    )


def run_preflight(request: PreflightRequest) -> PreflightReport:
    """Run every applicable rule group over ``request`` and assemble one advisory report.

    Never raises on an odd document: an empty ``files`` list, a ``main_file`` absent from
    ``files``, empty file content, and a request with no profile fields set all still produce a
    report, because this is called straight from an HTTP handler and a 500 here is strictly worse
    than an incomplete-looking report that explains itself via
    ``skipped``/``unresolved_includes``/``unexamined_files``.
    """
    files = {file.path: file.content for file in request.files}
    src = build_source(request.main_file, files)
    profile = request.profile

    # No-content path (fix round 1, ruling A/B/C) -- checked on `src`, i.e. AFTER build_source,
    # not before it: `unresolved_includes` still needs to come out of `src` even when there is
    # nothing else to report. The predicate reads `masked`, never `text`: a file containing only
    # "% TODO\n" has non-empty `text` but is entirely comment once masked, and must take this path
    # rather than falling through to four statement warnings on a blank template.
    if not src.files or all(not f.masked.strip() for f in src.files):
        return _no_content_report(src)

    raw: list[Finding] = []
    skipped: list[str] = []

    # Groups that always run (spec §3.1-§3.4), in catalogue order.
    raw.extend(check_crossref(src))
    raw.extend(check_bibliography(src, request.bib_content))
    raw.extend(check_statements(src, profile.required_statements))
    raw.extend(check_formatting(src))

    # anon (§3.5) only applies under double-blind review.
    if profile.double_blind:
        raw.extend(check_anonymity(src))
    else:
        skipped.append("anon")

    # length (§3.6) only applies when the author declared a limit.
    if profile.word_limit is not None:
        raw.extend(check_length(src, profile.word_limit))
    else:
        skipped.append("length")

    suppressed: list[str] = []
    suppressed_rules: set[str] = set()
    if src.unresolved_includes or src.unexamined_files:
        suppressed.extend(_CROSS_FILE_SUPPRESSED_RULES)
        suppressed_rules.update(_CROSS_FILE_SUPPRESSED_RULES)
    if profile.double_blind:
        applicable_double_blind = [
            rule
            for rule in _DOUBLE_BLIND_SUPPRESSED_RULES
            # .get(rule, ""): defensive only -- both operands are module constants, so a missing
            # entry can't happen from any request this function receives today. "" is never a
            # valid RequiredStatement, so a hypothetical future gap here just drops that one rule
            # from suppression instead of raising, keeping this function's "never raises on an odd
            # document" docstring promise unconditional rather than contingent on this dict.
            if _DOUBLE_BLIND_RULE_TO_STATEMENT.get(rule, "") in profile.required_statements
        ]
        suppressed.extend(applicable_double_blind)
        suppressed_rules.update(applicable_double_blind)

    # A file's real line count, in the same 1-based convention as PreflightSource.locate: the
    # number of "\n" in its original text, plus one.
    line_counts = {file.path: file.text.count("\n") + 1 for file in src.files}

    kept = [finding for finding in raw if finding.rule not in suppressed_rules and _within_bounds(finding, line_counts)]

    ordinals: dict[str, int] = {}
    findings: list[PreflightFinding] = []
    for finding in kept:
        n = ordinals.get(finding.rule, 0)
        ordinals[finding.rule] = n + 1
        group = finding.rule.partition(".")[0]
        findings.append(
            PreflightFinding(
                id=f"{finding.rule}:{n}",
                rule=finding.rule,
                group=group,
                severity=RULE_SEVERITY[finding.rule],
                file=finding.file,
                line=finding.line,
                symbol=finding.symbol,
                count=finding.count,
                excerpt=finding.excerpt,
            )
        )

    # Stable sort: findings sharing a severity keep the relative order they were appended in
    # above (catalogue group order, then each rule's own emission order).
    findings.sort(key=lambda f: _SEVERITY_ORDER.index(f.severity))

    counts = {severity: 0 for severity in _SEVERITY_ORDER}
    for finding in findings:
        counts[finding.severity] += 1

    return PreflightReport(
        findings=findings,
        counts=counts,
        skipped=skipped,
        suppressed=suppressed,
        unresolved_includes=list(src.unresolved_includes),
        unexamined_files=list(src.unexamined_files),
        no_content=False,
    )


def _within_bounds(finding: Finding, line_counts: dict[str, int]) -> bool:
    """``False`` only when ``finding.line`` is a real number that overshoots its file's length.

    ``line is None`` (no single meaningful location, e.g. a missing statement or an over-limit
    word count) always passes. A ``file`` the runner cannot find a line count for (never actually
    emitted by the six rule modules today, since every located finding is produced from a real
    offset in that same file's own text) also passes rather than being dropped on a guess.
    """
    if finding.line is None:
        return True
    total_lines = line_counts.get(finding.file)
    if total_lines is None:
        return True
    return finding.line <= total_lines
