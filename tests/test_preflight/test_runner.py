"""``run_preflight``: skip/suppression bookkeeping, severity, ids, ordering, line bounds."""

from __future__ import annotations

from src.models.preflight_schemas import (
    PreflightFile,
    PreflightProfile,
    PreflightReport,
    PreflightRequest,
)
from src.services.preflight.catalogue import PREFLIGHT_RULE_IDS, Finding
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


def test_every_emitted_rule_is_registered_in_the_catalogue():
    doc = "\\documentclass{IEEEtran}\n\\author{Jane Doe}\n\\linespread{0.9}\n\\ref{x}\n\\label{y}\n"
    rep = run_preflight(
        _req(doc, bib_content="@article{a, title={T}}", profile=PreflightProfile(double_blind=True, word_limit=5))
    )
    assert rep.findings
    for f in rep.findings:
        assert f.rule in PREFLIGHT_RULE_IDS


def test_findings_are_ordered_critical_first():
    doc = "\\label{unused}\n\\ref{ghost}\n"
    sev = [f.severity for f in run_preflight(_req(doc)).findings]
    assert sev == sorted(sev, key=["critical", "warning", "info"].index)


# --- additional coverage -------------------------------------------------------------------------


def test_empty_payload_reports_nothing_rather_than_erroring():
    """Robustness: an odd/incomplete request must produce a report, never an exception.

    An entirely empty ``files`` list means ``main_file`` itself cannot be resolved by
    ``build_source`` -- which is just another unresolved include from the runner's point of
    view, so the cross-file rules (``crossref.undefined_ref``, ``bib.uncited_entry``) go quiet.
    The always-on statement checks are a different story: there is genuinely no file content
    anywhere to satisfy a required statement, so correctly flagging all four as missing is the
    right behaviour, not a bug -- "reports nothing" describes the absence of a crash, not an
    empty findings list that would misrepresent a document that was never supplied.
    """
    rep = run_preflight(PreflightRequest(main_file="main.tex", files=[]))
    assert isinstance(rep, PreflightReport)
    assert rep.unresolved_includes == ["main.tex"]
    assert sorted(rep.suppressed) == ["bib.uncited_entry", "crossref.undefined_ref"]
    assert set(rep.skipped) == {"anon", "length"}
    assert [f.rule for f in rep.findings] == [
        "statement.data_availability_missing",
        "statement.ethics_missing",
        "statement.coi_missing",
        "statement.funding_missing",
    ]
    assert rep.counts == {"critical": 0, "warning": 4, "info": 0}

    # main_file simply absent from the supplied files -- same shape, still no exception.
    rep = run_preflight(PreflightRequest(main_file="main.tex", files=[PreflightFile(path="other.tex", content="x")]))
    assert isinstance(rep, PreflightReport)
    assert rep.unresolved_includes == ["main.tex"]

    # A file with empty content resolves cleanly.
    rep = run_preflight(PreflightRequest(main_file="main.tex", files=[PreflightFile(path="main.tex", content="")]))
    assert isinstance(rep, PreflightReport)
    assert rep.unresolved_includes == []

    # No profile fields set at all (the bare default).
    rep = run_preflight(_req("Text.\n"))
    assert isinstance(rep, PreflightReport)


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
