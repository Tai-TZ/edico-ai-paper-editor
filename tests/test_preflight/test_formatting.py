"""``check_formatting``: compressed leading, margin override, large negative vspace, font-size
override."""

from __future__ import annotations

from src.services.preflight.rules.formatting import check_formatting
from src.services.preflight.source import build_source


def _f(doc):
    return [x.rule for x in check_formatting(build_source("main.tex", {"main.tex": doc}))]


# --- brief's pinned tests, verbatim -------------------------------------------------------------


def test_leading_below_one_is_critical():
    assert "format.compressed_leading" in _f("\\linespread{0.92}\n")


def test_leading_at_or_above_one_is_fine():
    assert _f("\\linespread{1.0}\n") == []


def test_setstretch_and_baselinestretch_are_covered():
    assert "format.compressed_leading" in _f("\\setstretch{0.95}\n")
    assert "format.compressed_leading" in _f("\\renewcommand{\\baselinestretch}{0.9}\n")


def test_linespread_inside_a_listing_is_not_a_finding():
    doc = "\\begin{verbatim}\n\\linespread{0.8}\n\\end{verbatim}\n"
    assert _f(doc) == []


def test_margin_override_only_matters_for_a_venue_class():
    assert "format.margin_override" not in _f("\\documentclass{article}\n\\usepackage[margin=1in]{geometry}\n")
    assert "format.margin_override" in _f("\\documentclass{IEEEtran}\n\\usepackage[margin=1in]{geometry}\n")


def test_large_negative_vspace_is_counted_once_with_its_total():
    out = check_formatting(build_source("main.tex", {"main.tex": "\\vspace{-1em}\n\\vspace{-2em}\n\\vspace{-2pt}\n"}))
    hit = [f for f in out if f.rule == "format.large_negative_vspace"]
    assert len(hit) == 1 and hit[0].count == 2  # -2pt is small, not counted


# --- extra edge cases -----------------------------------------------------------------------


def test_compressed_leading_reports_the_line_and_the_raw_value():
    out = check_formatting(build_source("main.tex", {"main.tex": "Intro.\n\\linespread{0.9}\n"}))
    hit = [f for f in out if f.rule == "format.compressed_leading"]
    assert len(hit) == 1
    assert hit[0].line == 2
    assert hit[0].symbol == "0.9"


def test_non_numeric_leading_argument_does_not_crash_or_fire():
    assert _f("\\linespread{\\someMacro}\n") == []


def test_comma_decimal_leading_argument_is_not_valid_latex_and_is_ignored():
    assert _f("\\linespread{0,92}\n") == []


def test_linespread_inside_an_lstlisting_is_not_a_finding():
    doc = "\\begin{lstlisting}\n\\linespread{0.8}\n\\end{lstlisting}\n"
    assert _f(doc) == []


def test_leading_change_in_an_included_file_is_still_caught():
    files = {"main.tex": "\\input{sec/one}\n", "sec/one.tex": "\\linespread{0.9}\n"}
    out = check_formatting(build_source("main.tex", files))
    hit = [f for f in out if f.rule == "format.compressed_leading"]
    assert len(hit) == 1 and hit[0].file == "sec/one.tex"


def test_no_documentclass_at_all_is_treated_as_plain():
    # an \input-ed fragment: no \documentclass anywhere in the payload.
    files = {"main.tex": "\\input{body}\n", "body.tex": "\\usepackage[margin=1in]{geometry}\n"}
    assert "format.margin_override" not in [f.rule for f in check_formatting(build_source("main.tex", files))]


def test_margin_override_also_fires_on_an_explicit_length_register():
    doc = "\\documentclass{IEEEtran}\n\\setlength{\\textwidth}{7in}\n"
    out = check_formatting(build_source("main.tex", {"main.tex": doc}))
    hit = [f for f in out if f.rule == "format.margin_override"]
    assert len(hit) == 1 and hit[0].symbol == "textwidth"


def test_margin_override_reports_the_first_occurrence_with_the_total_count():
    doc = "\\documentclass{IEEEtran}\n\\usepackage{geometry}\n\\setlength{\\textwidth}{7in}\n"
    out = check_formatting(build_source("main.tex", {"main.tex": doc}))
    hit = [f for f in out if f.rule == "format.margin_override"]
    assert len(hit) == 1
    assert hit[0].count == 2
    assert hit[0].symbol == "geometry"
    assert hit[0].line == 2


def test_starred_vspace_is_covered():
    assert "format.large_negative_vspace" in _f("\\vspace*{-1em}\n")


def test_positive_vspace_is_not_large_negative_vspace():
    assert _f("\\vspace{1em}\n") == []


def test_bare_baselineskip_vspace_counts_as_one_unit():
    assert "format.large_negative_vspace" in _f("\\vspace{-\\baselineskip}\n")


def test_small_vspace_in_points_is_not_a_finding():
    assert _f("\\vspace{-2pt}\n") == []


def test_fontsize_in_the_body_is_reported():
    doc = "\\documentclass{article}\n\\begin{document}\n\\fontsize{8}{9}\\selectfont\nSmall.\n\\end{document}\n"
    out = check_formatting(build_source("main.tex", {"main.tex": doc}))
    hit = [f for f in out if f.rule == "format.font_size_override"]
    assert len(hit) == 1 and hit[0].symbol == "8"


def test_fontsize_in_the_preamble_is_not_reported():
    doc = "\\documentclass{article}\n\\fontsize{8}{9}\\selectfont\n\\begin{document}\nText.\n\\end{document}\n"
    assert _f(doc) == []


def test_fontsize_with_no_begin_document_treats_the_whole_file_as_body():
    # an \input-ed fragment never has its own \begin{document}, so \fontsize there is body text.
    files = {
        "main.tex": "\\documentclass{article}\n\\begin{document}\n\\input{frag}\n\\end{document}\n",
        "frag.tex": "\\fontsize{8}{9}\\selectfont\n",
    }
    out = check_formatting(build_source("main.tex", files))
    hit = [f for f in out if f.rule == "format.font_size_override"]
    assert len(hit) == 1 and hit[0].file == "frag.tex"
