"""``build_source``: comment/verbatim masking, offset-preserving ``locate``, and \\input resolution."""

from __future__ import annotations

from src.services.preflight.source import build_source

_PAPER = "Accuracy was 95\\% on test.\n% a real comment with \\label{ghost}\nText.\n"


def test_escaped_percent_is_not_a_comment():
    src = build_source("main.tex", {"main.tex": _PAPER})
    masked = src.masked_of("main.tex")
    assert "95\\% on test." in masked  # survives
    assert "ghost" not in masked  # the real comment is gone


def test_mask_preserves_offsets_and_line_count():
    src = build_source("main.tex", {"main.tex": _PAPER})
    masked = src.masked_of("main.tex")
    assert len(masked) == len(_PAPER)
    assert masked.count("\n") == _PAPER.count("\n")


def test_verbatim_body_is_masked():
    doc = "a\n\\begin{lstlisting}\n\\linespread{0.9}\n\\end{lstlisting}\nb\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "linespread" not in masked


def test_crlf_lines_match_the_frontend_split():
    doc = "one\r\ntwo\r\n\\label{x}\r\n"
    src = build_source("main.tex", {"main.tex": doc})
    assert src.locate("main.tex", doc.index("\\label")) == 3


def test_input_is_resolved_in_order():
    files = {"main.tex": "A\n\\input{sec/one}\n", "sec/one.tex": "\\label{deep}\n"}
    src = build_source("main.tex", files)
    assert [f.path for f in src.files] == ["main.tex", "sec/one.tex"]


def test_missing_input_is_recorded_not_raised():
    src = build_source("main.tex", {"main.tex": "\\input{nope}\n"})
    assert "nope.tex" in src.unresolved_includes


def test_input_cycle_terminates():
    files = {"a.tex": "\\input{b}\n", "b.tex": "\\input{a}\n"}
    src = build_source("a.tex", files)  # must return, not hang
    assert [f.path for f in src.files] == ["a.tex", "b.tex"]
    assert "a.tex" in src.unresolved_includes  # the back-edge is reported, not followed


def test_commented_out_input_is_not_followed():
    src = build_source("main.tex", {"main.tex": "% \\input{sec/one}\n"})
    assert src.unresolved_includes == ()


def test_diamond_include_is_not_unresolved():
    files = {
        "main.tex": "\\input{a}\n\\input{b}\n",
        "a.tex": "\\input{common}\n",
        "b.tex": "\\input{common}\n",
        "common.tex": "\\label{shared}\n",
    }
    src = build_source("main.tex", files)
    assert [f.path for f in src.files] == ["main.tex", "a.tex", "common.tex", "b.tex"]
    assert src.unresolved_includes == ()


def test_self_include_is_a_cycle():
    src = build_source("a.tex", {"a.tex": "\\input{a}\n"})
    assert [f.path for f in src.files] == ["a.tex"]
    assert "a.tex" in src.unresolved_includes
