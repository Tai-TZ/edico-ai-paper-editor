"""``run_preflight``: skip/suppression bookkeeping, severity, ids, ordering, line bounds, no-content."""

from __future__ import annotations

from src.models.preflight_schemas import (
    PreflightFile,
    PreflightProfile,
    PreflightReport,
    PreflightRequest,
)
from src.services.preflight.catalogue import PREFLIGHT_GROUPS, Finding
from src.services.preflight.runner import _within_bounds, run_preflight


def _req(doc="Text.\n", **kw):
    kw.setdefault("files", [PreflightFile(path="main.tex", content=doc)])
    return PreflightRequest(main_file="main.tex", **kw)


# --- brief's pinned tests, verbatim -------------------------------------------------------------


def test_report_is_advisory_and_counts_by_severity():
    rep = run_preflight(_req("\\ref{ghost}\n"))
    assert rep.integrity_mode == "comment_only"
    assert rep.counts["critical"] == 1


def test_findings_carry_stable_unique_ids():
    rep = run_preflight(_req("\\ref{a}\n\\ref{b}\n"))
    ids = [f.id for f in rep.findings]
    assert len(set(ids)) == len(ids)
    assert all(f.id.startswith(f.rule + ":") for f in rep.findings)


def test_undeclared_groups_are_skipped_not_silently_passed():
    rep = run_preflight(_req())
    assert set(rep.skipped) == {"anon", "length"}


def test_double_blind_suppresses_the_funding_statement_rule():
    rep = run_preflight(
        _req(profile=PreflightProfile(double_blind=True, required_statements=["funding", "author_contributions"]))
    )
    assert "statement.funding_missing" in rep.suppressed
    assert "statement.funding_missing" not in [f.rule for f in rep.findings]


def test_unresolved_includes_suppress_the_cross_file_rules():
    rep = run_preflight(_req("\\input{missing}\n\\ref{ghost}\n"))
    assert rep.unresolved_includes == ["missing.tex"]
    assert "crossref.undefined_ref" in rep.suppressed
    assert "crossref.undefined_ref" not in [f.rule for f in rep.findings]


def test_run_preflight_handles_a_document_hitting_every_rule_group_without_crashing():
    """Smoke/crash test, not a registration test -- deliberately renamed from "...is_registered_in_
    the_catalogue" (fix round 1, MINOR 4). ``RULE_SEVERITY[finding.rule]`` at ``runner.py`` raises
    ``KeyError`` for any rule id the catalogue does not know about, before any finding this test
    could inspect is ever returned -- so a loop re-checking registration here would be inert,
    unable to fail no matter what it finds. What this test actually demonstrates is that
    ``run_preflight`` does not crash when double-blind, a word limit, a bib file, and ordinary
    document content are all supplied together, exercising every one of the six rule modules in a
    single call. Real catalogue-registration coverage lives in
    ``tests/test_preflight/test_catalogue.py::test_every_rule_has_a_severity``.
    """
    doc = "\\documentclass{IEEEtran}\n\\author{Jane Doe}\n\\linespread{0.9}\n\\ref{x}\n\\label{y}\n"
    rep = run_preflight(
        _req(doc, bib_content="@article{a, title={T}}", profile=PreflightProfile(double_blind=True, word_limit=5))
    )
    assert rep.findings


def test_findings_are_ordered_critical_first():
    doc = "\\label{unused}\n\\ref{ghost}\n"
    sev = [f.severity for f in run_preflight(_req(doc)).findings]
    assert sev == sorted(sev, key=["critical", "warning", "info"].index)


# --- exact-value pins (fix round 1, IMPORTANT 1/2 and "tests the fixed suite must contain" 1-4) -


def test_double_blind_suppression_exact_set():
    """IMPORTANT 1: membership alone (``"x" in rep.suppressed``) does not catch over-suppression --
    a mutant that appends an unrelated rule id to the double-blind suppression list still passes a
    membership check. Pin the full set instead.

    ``required_statements`` deliberately lists all FIVE statement names, not just "funding" and
    "author_contributions" -- with ruling D (suppression intersected with what was actually
    required), a mutant that forges an extra suppression entry for e.g. "coi" is invisible unless
    "coi" is itself in ``required_statements``. Requiring all five here still pins exactly the same
    two real suppression ids (there is no third rule id in ``_DOUBLE_BLIND_SUPPRESSED_RULES`` to
    legitimately suppress), while giving a forged third entry somewhere to actually show up.
    """
    rep = run_preflight(
        _req(
            profile=PreflightProfile(
                double_blind=True,
                required_statements=["data_availability", "ethics", "coi", "funding", "author_contributions"],
            )
        )
    )
    assert sorted(rep.suppressed) == ["statement.author_contributions_missing", "statement.funding_missing"]


def test_cross_file_suppression_exact_set():
    """Same reasoning as above, for the other suppression family: unresolved includes drop exactly
    ``crossref.undefined_ref`` and ``bib.uncited_entry``, nothing more."""
    rep = run_preflight(_req("\\input{missing}\n\\ref{ghost}\n", bib_content="@article{a, title={T}}"))
    assert sorted(rep.suppressed) == ["bib.uncited_entry", "crossref.undefined_ref"]


def test_ordinals_are_per_rule_not_a_global_report_wide_counter():
    """IMPORTANT 2: ``test_ordinals_are_dense_per_rule_with_no_gaps`` below uses an input where all
    three matching findings belong to the SAME rule, so a global, report-wide ``enumerate`` counter
    coincidentally produces the same ``:0,:1,:2`` a correct per-rule counter would. This is the
    reviewer's own demonstration input: six findings, six DIFFERENT rules, so the real per-rule
    ordinal is ``:0`` for every one of them, while a global counter would instead number them
    ``:0,:1,:2,:3,:4,:5`` in whatever order they end up in -- a visibly different, and wrong, id
    list. Verified by hand-running ``run_preflight`` against this input before pinning it here.
    """
    rep = run_preflight(_req("\\ref{ghost}\n\\vspace{-3cm}\nx\n"))
    assert [f.id for f in rep.findings] == [
        "crossref.undefined_ref:0",
        "statement.data_availability_missing:0",
        "statement.ethics_missing:0",
        "statement.coi_missing:0",
        "statement.funding_missing:0",
        "format.large_negative_vspace:0",
    ]


def test_exact_ordered_findings_and_counts_for_a_document_hitting_several_groups():
    """A single document engineered to hit all six rule groups at once, so one test pins severity
    lookup, per-rule id assignment, critical-first ordering, AND the stable within-band order
    together -- MINOR 5's "no test pins the exact ordered findings list for a multi-group document"
    and the counts half of IMPORTANT 3's bundled test. Verified by hand-running ``run_preflight``
    against this exact input and comparing the printed ``(severity, id)`` pairs before pinning them
    here (the "print and compare before trusting a test" convention from task 9's own report).

    The document: an \\documentclass that isn't a plain class (anon.author_populated and
    format.margin_override's gate both care), a leaking \\author, a compressed \\linespread, an
    undefined \\ref and an unused \\label, a one-entry bib missing "journal"/"year"/a DOI and never
    cited, under double-blind review with a word limit low enough to be blown by two words.
    """
    doc = "\\documentclass{IEEEtran}\n\\author{Jane Doe}\n\\linespread{0.9}\n\\ref{x}\n\\label{y}\n"
    rep = run_preflight(
        _req(
            doc,
            bib_content="@article{a, title={T}}",
            profile=PreflightProfile(
                double_blind=True,
                word_limit=1,
                required_statements=["data_availability", "ethics", "coi", "funding"],
            ),
        )
    )
    assert [(f.severity, f.id) for f in rep.findings] == [
        ("critical", "crossref.undefined_ref:0"),
        ("critical", "format.compressed_leading:0"),
        ("critical", "anon.author_populated:0"),
        ("warning", "bib.missing_required_field:0"),
        ("warning", "bib.missing_required_field:1"),
        ("warning", "statement.data_availability_missing:0"),
        ("warning", "statement.ethics_missing:0"),
        ("warning", "statement.coi_missing:0"),
        # length.over_limit was `critical` (and so sat in the first band) until the final
        # whole-branch review demoted it to `warning` -- ruling 29. In the warning band the stable
        # sort keeps it last, because `length` is the last group the runner appends.
        ("warning", "length.over_limit:0"),
        ("info", "crossref.unused_label:0"),
        ("info", "bib.missing_doi:0"),
        ("info", "bib.uncited_entry:0"),
    ]
    assert rep.counts == {"critical": 3, "warning": 6, "info": 3}
    # statement.funding_missing is suppressed (double-blind, "funding" IS required here) -- not a
    # gap in the pinned list above, so pin it explicitly too.
    assert rep.suppressed == ["statement.funding_missing"]


# --- no-content path (fix round 1, ruling A/B/C; "tests the fixed suite must contain" 5-6) ------


def _assert_no_content_report(rep: PreflightReport, scenario: str, *, unresolved_includes: list[str]) -> None:
    """Shared assertions for the four no-content scenarios below.

    Fix round 2: ``_no_content_report`` (``runner.py``) builds a ``PreflightReport`` independently
    of the normal path, so the normal path's pin (``test_report_is_advisory_and_counts_by_severity``)
    never exercises it. A reviewer's mutation pass proved the gap: mutant ``counts={}`` (sparse
    instead of zero-filled) and mutant ``integrity_mode="BROKEN"`` each survived the full suite
    before this helper existed. ``scenario`` is passed to every assertion so a failure names which
    of the four callers broke, even though they share one assertion body.
    """
    assert isinstance(rep, PreflightReport), scenario
    assert rep.no_content is True, scenario
    assert rep.findings == [], scenario
    assert set(rep.skipped) == set(PREFLIGHT_GROUPS), scenario
    assert rep.suppressed == [], scenario
    assert rep.unresolved_includes == unresolved_includes, scenario
    assert rep.counts == {"critical": 0, "warning": 0, "info": 0}, scenario
    assert rep.integrity_mode == "comment_only", scenario


def test_no_content_when_files_is_empty():
    """An entirely empty ``files`` list means ``main_file`` itself cannot be resolved -- ruling B:
    that is still recorded in ``unresolved_includes`` (the only explanation the panel has left),
    but NOT in ``suppressed``, because the cross-file rules never ran at all here, let alone ran
    and got suppressed."""
    rep = run_preflight(PreflightRequest(main_file="main.tex", files=[]))
    _assert_no_content_report(rep, "files_is_empty", unresolved_includes=["main.tex"])


def test_no_content_when_main_file_is_absent_from_files():
    """Same shape as an empty ``files`` list -- ``main_file`` simply isn't one of the supplied
    paths, so it is just as unresolved."""
    rep = run_preflight(PreflightRequest(main_file="main.tex", files=[PreflightFile(path="other.tex", content="x")]))
    _assert_no_content_report(rep, "main_file_absent_from_files", unresolved_includes=["main.tex"])


def test_no_content_when_only_content_is_a_comment():
    """Ruling A's exact trap case: a file containing only ``% TODO\\n`` has non-empty ``text``, so
    a literal ``text == ""`` predicate would miss it and fall through to four statement warnings --
    the fresh-template noise this ruling exists to avoid. The predicate must read ``masked``.

    Unlike the two scenarios above, ``main_file`` here resolves cleanly (its text was supplied and
    is a real file in ``build_source``'s eyes) -- there is no missing \\input target to report, so
    ``unresolved_includes`` is correctly empty, not "non-empty for the same reason" as the other
    two no-content scenarios.
    """
    rep = run_preflight(
        PreflightRequest(main_file="main.tex", files=[PreflightFile(path="main.tex", content="% TODO\n")])
    )
    _assert_no_content_report(rep, "comment_only_content", unresolved_includes=[])


def test_no_content_when_only_content_is_whitespace():
    """Same reasoning as the comment-only case: ``text`` is non-empty, ``masked`` is blank once
    stripped, and ``main_file`` resolves cleanly so ``unresolved_includes`` stays empty."""
    rep = run_preflight(
        PreflightRequest(main_file="main.tex", files=[PreflightFile(path="main.tex", content="   \n  \n")])
    )
    _assert_no_content_report(rep, "whitespace_only_content", unresolved_includes=[])


def test_no_content_is_false_for_a_document_with_real_content():
    rep = run_preflight(_req("Text.\n"))
    assert rep.no_content is False


# --- ruling D: double-blind suppression intersected with required_statements --------------------


def test_double_blind_suppression_records_nothing_when_no_statement_is_required():
    """Ruling D: recording ``statement.funding_missing`` as suppressed when the profile's
    ``required_statements`` never asked for a funding statement in the first place is a small lie
    the panel would have to render. With an empty ``required_statements``, neither suppressed id
    is recorded."""
    rep = run_preflight(_req(profile=PreflightProfile(double_blind=True, required_statements=[])))
    assert rep.suppressed == []


def test_double_blind_suppression_records_only_the_required_statement():
    """With only "funding" required, only ``statement.funding_missing`` is recorded as suppressed
    -- ``statement.author_contributions_missing`` is not, because that statement was never
    required here and so was never a candidate finding to suppress in the first place."""
    rep = run_preflight(_req(profile=PreflightProfile(double_blind=True, required_statements=["funding"])))
    assert rep.suppressed == ["statement.funding_missing"]


# --- additional coverage -------------------------------------------------------------------------


def test_always_on_groups_are_never_skipped():
    rep = run_preflight(_req(profile=PreflightProfile(double_blind=True, word_limit=100)))
    assert rep.skipped == []


def test_no_suppression_or_unresolved_includes_when_nothing_conflicts():
    rep = run_preflight(_req("Text.\n"))
    assert rep.suppressed == []
    assert rep.unresolved_includes == []


def test_author_contributions_statement_is_also_suppressed_under_double_blind():
    rep = run_preflight(
        _req(profile=PreflightProfile(double_blind=True, required_statements=["funding", "author_contributions"]))
    )
    assert "statement.author_contributions_missing" in rep.suppressed
    assert "statement.author_contributions_missing" not in [f.rule for f in rep.findings]


def test_bib_uncited_entry_is_also_suppressed_on_unresolved_includes():
    rep = run_preflight(_req("\\input{missing}\n", bib_content="@article{a, title={T}}"))
    assert "bib.uncited_entry" in rep.suppressed
    assert "bib.uncited_entry" not in [f.rule for f in rep.findings]


def test_finding_group_matches_its_rule_prefix():
    rep = run_preflight(_req("\\ref{ghost}\n\\label{unused}\n"))
    assert rep.findings
    for f in rep.findings:
        assert f.group == f.rule.split(".")[0]


def test_ordinals_are_dense_per_rule_with_no_gaps():
    rep = run_preflight(_req("\\ref{a}\n\\ref{b}\n\\ref{c}\n"))
    undefined = [f.id for f in rep.findings if f.rule == "crossref.undefined_ref"]
    assert undefined == ["crossref.undefined_ref:0", "crossref.undefined_ref:1", "crossref.undefined_ref:2"]


def test_within_bounds_drops_a_finding_past_its_files_real_line_count():
    # None of the six rule modules can actually produce this today -- every located finding is
    # computed from a real offset inside that same file's own text, so its line can never exceed
    # that file's real line count. This exercises the defensive filter directly as insurance
    # against a future rule module getting a line number wrong.
    finding = Finding(rule="crossref.undefined_ref", file="main.tex", line=5, symbol="x")
    assert _within_bounds(finding, {"main.tex": 3}) is False
    assert _within_bounds(finding, {"main.tex": 5}) is True
    assert _within_bounds(finding, {"main.tex": 6}) is True


def test_within_bounds_passes_a_none_line_through_untouched():
    finding = Finding(rule="statement.funding_missing", file="main.tex", line=None)
    assert _within_bounds(finding, {}) is True


def test_within_bounds_passes_an_unresolvable_file_through_rather_than_guessing():
    finding = Finding(rule="crossref.undefined_ref", file="ghost.tex", line=100)
    assert _within_bounds(finding, {"main.tex": 3}) is True


# --- final whole-branch review, FIX 3: an unexamined payload file suppresses the same rules ------


def _two_file_req(command):
    return PreflightRequest(
        main_file="main.tex",
        files=[
            PreflightFile(
                path="main.tex",
                content=f"\\begin{{document}}\n{command}\nSee \\ref{{fig:one}} and \\ref{{tab:two}}.\n\\end{{document}}\n",
            ),
            PreflightFile(path="sections/intro.tex", content="\\label{fig:one}\n\\label{tab:two}\nprose\n"),
        ],
    )


def test_an_unexamined_payload_file_suppresses_the_cross_file_rules():
    # \subfile and \InputIfFileExists leave sections/intro.tex unread even though it is right
    # there in the payload. Before FIX 3 every bookkeeping field stayed empty and the runner
    # reported two `critical` undefined refs over labels it had never opened -- the exact
    # inversion of spec §4.3's "thà im lặng còn hơn bắn critical dựa trên dữ liệu thiếu".
    for command in ("\\subfile{sections/intro}", "\\InputIfFileExists{sections/intro.tex}{}{}"):
        rep = run_preflight(_two_file_req(command))
        assert [f for f in rep.findings if f.severity == "critical"] == [], command
        assert rep.unexamined_files == ["sections/intro.tex"], command
        assert rep.unresolved_includes == [], command
        assert rep.suppressed == ["crossref.undefined_ref", "bib.uncited_entry"], command


def test_a_resolved_input_graph_still_reports_a_real_undefined_ref_as_critical():
    # The true-positive control for the suppression above.
    rep = run_preflight(_two_file_req("\\input{sections/intro}"))
    assert rep.unexamined_files == []
    assert rep.suppressed == []
    rep = run_preflight(
        PreflightRequest(
            main_file="main.tex",
            files=[
                PreflightFile(
                    path="main.tex",
                    content="\\begin{document}\n\\input{sections/intro}\nSee \\ref{fig:typo}.\n\\end{document}\n",
                ),
                PreflightFile(path="sections/intro.tex", content="\\label{fig:one}\nprose\n"),
            ],
        )
    )
    assert [(f.severity, f.rule, f.symbol) for f in rep.findings if f.severity == "critical"] == [
        ("critical", "crossref.undefined_ref", "fig:typo")
    ]


def test_both_cross_file_causes_are_reported_in_their_own_fields():
    rep = run_preflight(
        PreflightRequest(
            main_file="main.tex",
            files=[
                PreflightFile(
                    path="main.tex",
                    content="\\begin{document}\n\\input{sections/gone}\n\\subfile{sections/intro}\n\\end{document}\n",
                ),
                PreflightFile(path="sections/intro.tex", content="\\label{fig:one}\nprose\n"),
            ],
        )
    )
    assert rep.unresolved_includes == ["sections/gone.tex"]
    assert rep.unexamined_files == ["sections/intro.tex"]
    assert rep.suppressed == ["crossref.undefined_ref", "bib.uncited_entry"]
