"""``check_statements``: required submission-disclosure rules (data availability, ethics, coi,
funding, author contributions)."""

from __future__ import annotations

from src.services.preflight.rules.statements import check_statements
from src.services.preflight.source import build_source

_ALL = ["data_availability", "ethics", "coi", "funding", "author_contributions"]


# --- brief's pinned tests, verbatim -------------------------------------------------------------


def test_empty_paper_misses_every_requested_statement():
    out = check_statements(build_source("main.tex", {"main.tex": "Text.\n"}), _ALL)
    assert len(out) == 5


def test_a_heading_satisfies_the_statement():
    doc = "\\section{Data Availability}\nOn request.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"])
    assert out == []


def test_an_inline_phrase_satisfies_the_statement():
    doc = "The data supporting the findings are available upon request.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"])
    assert out == []


def test_vietnamese_heading_is_recognised():
    doc = "\\section{Xung đột lợi ích}\nKhông có.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["coi"])
    assert out == []


def test_a_statement_in_an_included_file_counts():
    files = {"main.tex": "\\input{back}\n", "back.tex": "\\section{Funding}\nNSF.\n"}
    assert check_statements(build_source("main.tex", files), ["funding"]) == []


def test_only_requested_statements_are_checked():
    out = check_statements(build_source("main.tex", {"main.tex": "Text.\n"}), ["ethics"])
    assert [f.rule for f in out] == ["statement.ethics_missing"]


# --- extra edge cases -----------------------------------------------------------------------


def test_missing_finding_has_no_line_and_names_the_statement_in_symbol():
    out = check_statements(build_source("main.tex", {"main.tex": "Text.\n"}), ["ethics"])
    assert out[0].file == "main.tex"
    assert out[0].line is None
    assert out[0].symbol == "ethics"


def test_each_requested_statement_maps_to_its_own_rule_id():
    out = check_statements(build_source("main.tex", {"main.tex": "Text.\n"}), _ALL)
    assert sorted(f.rule for f in out) == [
        "statement.author_contributions_missing",
        "statement.coi_missing",
        "statement.data_availability_missing",
        "statement.ethics_missing",
        "statement.funding_missing",
    ]


def test_an_unrecognised_required_name_is_ignored_not_raised():
    out = check_statements(build_source("main.tex", {"main.tex": "Text.\n"}), ["not_a_real_statement"])
    assert out == []


def test_an_unrelated_heading_does_not_satisfy_a_different_statement():
    doc = "\\section{Funding}\nNSF.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["ethics"])
    assert [f.rule for f in out] == ["statement.ethics_missing"]


def test_matching_is_case_insensitive():
    doc = "\\SECTION{DATA AVAILABILITY}\nSee repository.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"]) == []


def test_unaccented_vietnamese_phrase_is_recognised():
    doc = "Nghien cuu nay khong co xung dot loi ich.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["coi"]) == []


def test_credit_satisfies_author_contributions():
    doc = "CRediT: J.D. wrote the manuscript; A.B. ran the experiments.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["author_contributions"]) == []


def test_declare_no_competing_interests_phrase_satisfies_coi():
    doc = "The authors declare no competing interests.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["coi"]) == []


def test_acknowledgements_environment_satisfies_funding():
    doc = "\\begin{acknowledgements}\nThis work was supported.\n\\end{acknowledgements}\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["funding"]) == []


def test_bare_grant_in_prose_satisfies_funding_deliberately_broad():
    doc = "We are grateful for the grant of access to the dataset.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["funding"]) == []


def test_commented_out_statement_does_not_count():
    doc = "% \\section{Data Availability}\n% Available upon request.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"])
    assert [f.rule for f in out] == ["statement.data_availability_missing"]


def test_bare_ethical_discussing_the_topic_does_not_satisfy_ethics():
    # A paper whose subject IS research ethics uses the word constantly without ever disclosing
    # an approval. Crediting it with a disclosure it never made is the false "present" this rule
    # must avoid (see the comment on _ETHICS_HEADING_ONLY_TERMS in statements.py).
    doc = (
        "\\section{Introduction}\n"
        "This paper studies the ethical implications of automated decision-making. "
        "We argue that ethical frameworks must adapt to new technology, and that ethical "
        "review of algorithms is a growing concern across many ethical traditions.\n"
    )
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["ethics"])
    assert [f.rule for f in out] == ["statement.ethics_missing"]


def test_ethics_approval_phrase_satisfies_ethics():
    doc = "Ethical approval was obtained from the institutional review board.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["ethics"]) == []


def test_bare_ethics_heading_is_accepted_as_a_deliberate_disclosure_signal():
    doc = "\\section{Ethics}\nNone required.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["ethics"]) == []


# --- fix round 1: widened data-availability phrasing (IMPORTANT 1, 2) ------------------------


def test_corresponding_author_on_reasonable_request_is_recognised():
    doc = (
        "The datasets generated during this study are available from the corresponding author on reasonable request.\n"
    )
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"]) == []


def test_available_in_main_text_or_supplementary_is_recognised():
    doc = "All data are available in the main text or the supplementary materials.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"]) == []


def test_available_and_request_across_a_sentence_boundary_does_not_satisfy():
    # The widened gap between "available" and its tail term is bounded to 80 non-period
    # characters precisely so it cannot bleed across a sentence boundary: "available" ending one
    # sentence and an unrelated "request" appearing in the next sentence must not pair up.
    doc = "The code is available. If you need something, please submit a request.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"])
    assert [f.rule for f in out] == ["statement.data_availability_missing"]


# --- fix round 1: heading-less CRediT role list (IMPORTANT 3) --------------------------------


def test_credit_role_list_without_a_heading_is_recognised():
    doc = "Conceptualization, A.B.; methodology, C.D.\n"
    assert check_statements(build_source("main.tex", {"main.tex": doc}), ["author_contributions"]) == []


def test_ordinary_methodology_and_resources_sections_do_not_satisfy_contributions():
    # The trap: Methodology and Resources are both CRediT taxonomy roles AND ordinary section
    # titles. A detector that fires on the bare role word would satisfy author_contributions on
    # nearly every paper in existence. Neither section here is followed by ", initials" or
    # chained to another role by a semicolon, so this must stay missing.
    doc = "\\section{Methodology}\nWe did things.\n\\section{Resources}\nWe used things.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["author_contributions"])
    assert [f.rule for f in out] == ["statement.author_contributions_missing"]


def test_repeated_single_role_list_does_not_satisfy_contributions():
    # Two attributions but the SAME role repeated — not two distinct roles, so this must not be
    # mistaken for a real contributions block by this detector alone (the heading/phrase table is
    # the correct place to recognise a two-person, one-role credit line, not the shape detector).
    doc = "Methodology, A.B.; Methodology, C.D.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["author_contributions"])
    assert [f.rule for f in out] == ["statement.author_contributions_missing"]


# --- fix round 1: Vietnamese acknowledgements heading satisfies funding (IMPORTANT 4) ---------


def test_vietnamese_acknowledgements_heading_satisfies_funding():
    for heading in ("Lời cảm ơn", "Loi cam on"):
        doc = f"\\section{{{heading}}}\nCảm ơn Quỹ X.\n"
        assert check_statements(build_source("main.tex", {"main.tex": doc}), ["funding"]) == []
