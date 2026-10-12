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


# --- final whole-branch review, FIX 5: a % comment on a \begin/\end physical line ---------------


def test_a_comment_on_a_begin_verbatim_line_is_masked():
    doc = "\\begin{lstlisting} % \\linespread{0.5} squeeze\ncode\n\\end{lstlisting}\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "linespread" not in masked
    assert "\\begin{lstlisting}" in masked  # the token itself must survive -- rules match on it


def test_a_comment_on_an_end_verbatim_line_is_masked():
    doc = "\\begin{verbatim}\ncode\n\\end{verbatim} % \\linespread{0.5}\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "linespread" not in masked
    assert "\\end{verbatim}" in masked


def test_a_ref_inside_a_comment_on_a_begin_line_is_masked():
    doc = "\\begin{verbatim} % see \\ref{fig:nonexistent}\ncode\n\\end{verbatim}\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "fig:nonexistent" not in masked


def test_real_source_after_an_end_verbatim_on_the_same_line_is_not_masked():
    # The counter-case to the two above: without a `%` the rest of an \end line is real source.
    doc = "\\begin{verbatim}\ncode\n\\end{verbatim} \\linespread{0.5}\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "\\linespread{0.5}" in masked


def test_an_escaped_percent_on_a_begin_line_does_not_start_a_comment():
    doc = "\\begin{lstlisting}[caption=50\\% off \\linespread{0.5}]\ncode\n\\end{lstlisting}\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "\\linespread{0.5}" in masked


def test_a_comment_opened_on_a_begin_line_still_resumes_inside_the_verbatim_body():
    # The comment ends at the newline; what follows is the environment's body and must stay masked.
    doc = "\\begin{verbatim} % note\n\\linespread{0.5}\n\\end{verbatim}\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "linespread" not in masked
    assert len(masked) == len(doc)
    assert masked.count("\n") == doc.count("\n")


# --- final whole-branch review, FIX 3: payload files the include graph never reached -------------

_INTRO = "\\label{fig:one}\n\\label{tab:two}\nSome prose.\n"


def test_a_subfile_target_present_in_the_payload_is_recorded_as_unexamined():
    # \subfile is not \input, so build_source never opens sections/intro.tex -- but the file IS
    # there, so it must not land in unresolved_includes (nothing is missing).
    files = {
        "main.tex": "\\begin{document}\n\\subfile{sections/intro}\n\\end{document}\n",
        "sections/intro.tex": _INTRO,
    }
    src = build_source("main.tex", files)
    assert src.unexamined_files == ("sections/intro.tex",)
    assert src.unresolved_includes == ()


def test_inputiffileexists_import_and_subimport_targets_are_all_recorded():
    for command in (
        "\\InputIfFileExists{sections/intro.tex}{}{}",
        "\\import{sections/}{intro}",
        "\\subimport{sections/}{intro}",
        "\\includeonly{sections/intro}",
    ):
        files = {
            "main.tex": f"\\begin{{document}}\n{command}\n\\end{{document}}\n",
            "sections/intro.tex": _INTRO,
        }
        src = build_source("main.tex", files)
        assert src.unexamined_files == ("sections/intro.tex",), command
        assert src.unresolved_includes == (), command


def test_a_resolved_input_graph_has_no_unexamined_files():
    # The counter-case: a file the graph DOES reach must never be recorded, or every multi-file
    # project would permanently suppress its own cross-file rules.
    files = {
        "main.tex": "\\begin{document}\n\\input{sections/intro}\n\\end{document}\n",
        "sections/intro.tex": _INTRO,
    }
    assert build_source("main.tex", files).unexamined_files == ()


def test_a_non_tex_payload_entry_is_never_unexamined():
    # A .bib (or a .cls, or a .sty) is not source the include graph is meant to reach.
    files = {
        "main.tex": "\\begin{document}\nprose\n\\end{document}\n",
        "refs.bib": "@article{a, title={T}}",
        "venue.cls": "% class file\n",
    }
    assert build_source("main.tex", files).unexamined_files == ()


def test_a_latex_extension_and_an_uppercase_extension_both_count_as_source():
    files = {
        "main.tex": "\\begin{document}\nprose\n\\end{document}\n",
        "appendix.latex": _INTRO,
        "extra.TEX": _INTRO,
    }
    assert set(build_source("main.tex", files).unexamined_files) == {"appendix.latex", "extra.TEX"}


def test_a_missing_input_target_still_goes_to_unresolved_includes_only():
    files = {"main.tex": "\\begin{document}\n\\input{sections/gone}\n\\end{document}\n"}
    src = build_source("main.tex", files)
    assert src.unresolved_includes == ("sections/gone.tex",)
    assert src.unexamined_files == ()
