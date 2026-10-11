"""``check_crossref``: undefined refs, duplicate labels, label-less floats, unused labels."""

from __future__ import annotations

from src.services.preflight.rules.crossref import check_crossref
from src.services.preflight.source import build_source


def _rules(doc, extra=None):
    files = {"main.tex": doc, **(extra or {})}
    return [f.rule for f in check_crossref(build_source("main.tex", files))]


def test_ref_without_label_is_reported():
    out = check_crossref(build_source("main.tex", {"main.tex": "See \\ref{fig:a}.\n"}))
    assert [(f.rule, f.symbol, f.line) for f in out] == [("crossref.undefined_ref", "fig:a", 1)]


def test_label_in_an_included_file_satisfies_the_ref():
    assert "crossref.undefined_ref" not in _rules(
        "\\input{sec/one}\nSee \\ref{fig:a}.\n", extra={"sec/one.tex": "\\label{fig:a}\n"}
    )


def test_newcommand_wrapping_ref_does_not_report_the_parameter():
    assert _rules("\\newcommand{\\myref}[1]{\\ref{#1}}\n") == []


def test_cref_and_eqref_are_covered():
    assert _rules("\\eqref{eq:1} \\cref{sec:2}\n").count("crossref.undefined_ref") == 2


def test_duplicate_label_is_reported_once_per_extra_definition():
    assert _rules("\\label{x}\n\\label{x}\n").count("crossref.duplicate_label") == 1


def test_float_without_label_is_reported():
    assert "crossref.float_without_label" in _rules("\\begin{figure}\\includegraphics{a}\\end{figure}\n")


def test_unused_label_is_info_not_silence():
    assert "crossref.unused_label" in _rules("\\label{unused}\n")


def test_commented_ref_is_ignored():
    assert _rules("% \\ref{ghost}\n") == []


# --- extra edge cases -----------------------------------------------------------------------


def test_a_labeled_and_referenced_float_is_entirely_clean():
    doc = "\\begin{figure}\\label{fig:ok}\\end{figure}\nSee \\ref{fig:ok}.\n"
    assert _rules(doc) == []


def test_a_single_commands_comma_list_yields_one_reference_per_key():
    out = check_crossref(build_source("main.tex", {"main.tex": "\\cref{a,b}\n"}))
    assert sorted(f.symbol for f in out if f.rule == "crossref.undefined_ref") == ["a", "b"]


def test_duplicate_count_scales_with_extra_definitions():
    assert _rules("\\label{y}\n\\label{y}\n\\label{y}\n").count("crossref.duplicate_label") == 2


def test_duplicate_label_is_still_only_one_unused_finding():
    out = _rules("\\label{z}\n\\label{z}\n")
    assert out.count("crossref.duplicate_label") == 1
    assert out.count("crossref.unused_label") == 1


def test_table_and_algorithm_floats_are_also_checked():
    out = _rules("\\begin{table}data\\end{table}\n\\begin{algorithm}steps\\end{algorithm}\n")
    assert out.count("crossref.float_without_label") == 2


def test_commented_out_float_is_ignored():
    assert _rules("% \\begin{figure}\\end{figure}\n") == []


def test_nameref_is_not_a_tracked_reference_command():
    # \nameref is not in the covered set (ref, eqref, autoref, cref, Cref, pageref, vref).
    assert _rules("\\nameref{x}\n") == []


def test_undefined_ref_is_reported_once_per_key_with_an_occurrence_count():
    doc = "See \\ref{fig:a}.\nAlso \\ref{fig:a}.\nAnd \\ref{fig:a}.\n"
    out = [f for f in check_crossref(build_source("main.tex", {"main.tex": doc})) if f.rule == "crossref.undefined_ref"]
    assert len(out) == 1
    assert out[0].symbol == "fig:a"
    assert out[0].count == 3
    assert out[0].line == 1
