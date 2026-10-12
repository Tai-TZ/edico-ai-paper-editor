"""``count_body_words`` / ``check_length``: the word-count estimate and its over/near-limit
findings."""

from __future__ import annotations

from src.services.preflight.rules.length import check_length, count_body_words
from src.services.preflight.source import build_source


def _src(doc):
    return build_source("main.tex", {"main.tex": doc})


# --- brief's pinned tests, verbatim -------------------------------------------------------------


def test_preamble_and_comments_are_not_counted():
    doc = "\\documentclass{article}\n\\begin{document}\n% ignored words here\nOne two three.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 3


def test_math_is_not_counted_but_captions_are():
    doc = "\\begin{document}\nValue $x + y = z$ holds.\n\\caption{Two words}\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 4  # Value, holds, Two, words


def test_included_file_words_are_counted():
    files = {"main.tex": "\\begin{document}\n\\input{a}\n\\end{document}\n", "a.tex": "one two\n"}
    assert count_body_words(build_source("main.tex", files)) == 2


def test_over_limit_is_critical_and_carries_the_count():
    doc = "\\begin{document}\n" + "word " * 50 + "\n\\end{document}\n"
    out = check_length(_src(doc), 10)
    assert [(f.rule, f.count) for f in out] == [("length.over_limit", 50)]


def test_just_under_the_limit_warns_near():
    doc = "\\begin{document}\n" + "word " * 98 + "\n\\end{document}\n"
    assert [f.rule for f in check_length(_src(doc), 100)] == ["length.near_limit"]


def test_comfortably_under_the_limit_is_silent():
    doc = "\\begin{document}\nword\n\\end{document}\n"
    assert check_length(_src(doc), 100) == []


# --- extra edge cases -----------------------------------------------------------------------


def test_display_dollar_math_is_not_counted():
    doc = "\\begin{document}\nDouble $$x+y$$ display math test.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 4  # Double, display, math, test.


def test_paren_and_bracket_math_are_not_counted():
    doc = "\\begin{document}\nSee \\(x+y\\) and \\[a+b\\] done.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 3  # See, and, done.


def test_equation_environment_is_not_counted():
    doc = "\\begin{document}\nSee eq. \\begin{equation}\nx = y + z\n\\end{equation}\nDone here.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 4  # See, eq., Done, here.


def test_align_environment_is_not_counted():
    doc = "\\begin{document}\nBefore.\n\\begin{align}\na &= b + c\n\\end{align}\nAfter.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 2  # Before., After.


def test_bibliography_command_truncates_the_rest_of_the_body():
    doc = "\\begin{document}\nIntro text.\n\\bibliography{refs}\nAppendix leftover words here.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 2  # Intro, text. -- nothing after \bibliography counts


def test_manual_bibliography_environment_truncates_the_rest_of_the_body():
    doc = (
        "\\begin{document}\nmanual refs:\n"
        "\\begin{thebibliography}{9}\n\\bibitem{a} Some Title Words\n\\end{thebibliography}\n"
        "\\end{document}\n"
    )
    assert count_body_words(_src(doc)) == 2  # manual, refs: -- the hand-typed entries don't count


def test_fragment_with_no_document_environment_is_entirely_body():
    doc = "Plain fragment with $x+y$ math and text.\n"
    assert count_body_words(_src(doc)) == 6  # Plain, fragment, with, math, and, text.


def test_escaped_dollar_is_not_mistaken_for_a_math_delimiter():
    doc = "\\begin{document}\nThe cost is \\$5 and later \\$10 total.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 8


def test_at_exactly_the_limit_is_near_not_over():
    doc = "\\begin{document}\n" + "word " * 100 + "\n\\end{document}\n"
    assert [f.rule for f in check_length(_src(doc), 100)] == ["length.near_limit"]


def test_one_over_the_limit_is_over_not_near():
    doc = "\\begin{document}\n" + "word " * 101 + "\n\\end{document}\n"
    assert [f.rule for f in check_length(_src(doc), 100)] == ["length.over_limit"]


def test_finding_has_no_line_and_carries_the_limit_in_symbol():
    doc = "\\begin{document}\n" + "word " * 50 + "\n\\end{document}\n"
    out = check_length(_src(doc), 10)
    assert len(out) == 1
    assert out[0].file == "main.tex"
    assert out[0].line is None
    assert out[0].symbol == "10"


def test_over_limit_and_near_limit_never_fire_together():
    for word_count in (0, 1, 94, 95, 99, 100, 101, 200):
        doc = "\\begin{document}\n" + "word " * word_count + "\n\\end{document}\n"
        out = check_length(_src(doc), 100)
        assert len(out) <= 1
