"""``collect_cite_keys`` / ``check_bibliography``: cite-key hygiene and BibTeX entry hygiene."""

from __future__ import annotations

from src.services.preflight.rules.bibliography import check_bibliography, collect_cite_keys
from src.services.preflight.source import build_source

_BIB = """@article{ok, title={T}, author={A}, journal={J}, year={2020}, doi={10.1/x}}"""


# --- brief's pinned tests, verbatim -------------------------------------------------------------


def test_cite_key_absent_from_bib_is_critical():
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{ghost}\n"}), _BIB)
    assert ("bib.cite_key_missing", "ghost") in [(f.rule, f.symbol) for f in out]


def test_capitalized_natbib_cite_counts_as_a_citation():
    # CITE_RE in parser/latex.py matches only lowercase "cite"; preflight must still see this
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\Citep{ok}\n"}), _BIB)
    assert "bib.uncited_entry" not in [f.rule for f in out]


def test_commented_cite_does_not_count_as_a_citation():
    out = check_bibliography(build_source("main.tex", {"main.tex": "% \\cite{ok}\n"}), _BIB)
    assert "bib.uncited_entry" in [f.rule for f in out]


def test_article_missing_journal_is_reported():
    bib = "@article{a, title={T}, author={A}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert ("bib.missing_required_field", "journal") in [(f.rule, f.symbol) for f in out]


def test_entries_sharing_a_doi_are_duplicates():
    bib = (
        "@article{a, title={One}, doi={10.1/x}, journal={J}, year={2020}}\n"
        "@article{b, title={Two}, doi={10.1/X}, journal={J}, year={2021}}"
    )
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\\cite{b}\n"}), bib)
    assert "bib.duplicate_entry" in [f.rule for f in out]


def test_entry_without_doi_or_eprint_is_info():
    # Full finding set, not membership: a book with a populated publisher must report ONLY
    # bib.missing_doi. The loose "in" form of this assertion is what let a prior bug through —
    # bib.missing_required_field used to fire on "publisher" unconditionally for every @book
    # (see test_book_without_publisher_is_reported and friends below for the field itself).
    bib = "@book{b, title={T}, author={A}, publisher={P}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert [(f.rule, f.symbol) for f in out] == [("bib.missing_doi", "b")]


def test_no_bib_content_reports_nothing_rather_than_everything():
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), "")
    assert out == []


# --- extra edge cases -----------------------------------------------------------------------


def test_entry_with_eprint_but_no_doi_is_not_missing_doi():
    bib = "@article{a, title={T}, journal={J}, year={2020}, eprint={2101.00001}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert "bib.missing_doi" not in [f.rule for f in out]


def test_entries_sharing_a_normalized_title_without_a_doi_are_duplicates():
    bib = (
        "@article{a, title={Attention Is All You Need}, journal={J}, year={2017}}\n"
        "@article{b, title={attention is all you need.}, journal={J}, year={2017}}"
    )
    out = [
        f
        for f in check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\\cite{b}\n"}), bib)
        if f.rule == "bib.duplicate_entry"
    ]
    assert len(out) == 1
    assert out[0].count == 2


def test_entries_without_doi_or_title_are_not_treated_as_duplicates_of_each_other():
    bib = "@misc{a, year={2020}}\n@misc{b, year={2021}}"
    out = [
        f
        for f in check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\\cite{b}\n"}), bib)
        if f.rule == "bib.duplicate_entry"
    ]
    assert out == []


def test_unknown_entry_type_only_requires_a_title():
    bib = "@misc{a, title={T}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_missing_title_is_reported_for_any_entry_type():
    bib = "@article{a, journal={J}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert ("bib.missing_required_field", "title") in [(f.rule, f.symbol) for f in out]


def test_nocite_only_key_is_not_a_real_citation():
    # \nocite matches CITE_RE's pattern but extract_cite_keys deliberately excludes it.
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\nocite{ok}\n"}), _BIB)
    assert "bib.uncited_entry" in [f.rule for f in out]


def test_capitalized_cite_with_pre_and_post_notes_is_still_recognized():
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\Citep[see][p. 3]{ok}\n"}), _BIB)
    assert "bib.uncited_entry" not in [f.rule for f in out]


def test_cite_key_missing_is_reported_once_per_key_with_an_occurrence_count():
    doc = "\\cite{ghost}\\cite{ghost}\n"
    out = [
        f
        for f in check_bibliography(build_source("main.tex", {"main.tex": doc}), _BIB)
        if f.rule == "bib.cite_key_missing"
    ]
    assert len(out) == 1
    assert out[0].symbol == "ghost"


# --- raw-only required-field presence checks (publisher/booktitle/school) ----------------------
# parse_bib_entries never puts these three fields in its parsed dict (only key, type, title,
# author, year, doi, eprint, journal, raw come back — src/services/parser/latex.py:159-169), so
# _field_is_present falls back to a presence scan over raw text for them. Each pair below proves
# that is a real presence check and not an unconditional miss: present -> quiet, absent -> flagged.


def test_populated_book_publisher_is_not_reported():
    bib = "@book{b, title={T}, author={A}, publisher={P}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_book_without_publisher_is_reported():
    bib = "@book{b, title={T}, author={A}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert ("bib.missing_required_field", "publisher") in [(f.rule, f.symbol) for f in out]


def test_populated_inproceedings_booktitle_is_not_reported():
    bib = "@inproceedings{a, title={T}, booktitle={NeurIPS}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_inproceedings_without_booktitle_is_reported():
    bib = "@inproceedings{a, title={T}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert ("bib.missing_required_field", "booktitle") in [(f.rule, f.symbol) for f in out]


def test_populated_conference_booktitle_is_not_reported():
    bib = "@conference{a, title={T}, booktitle={ICML}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_conference_without_booktitle_is_reported():
    bib = "@conference{a, title={T}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert ("bib.missing_required_field", "booktitle") in [(f.rule, f.symbol) for f in out]


def test_populated_phdthesis_school_is_not_reported():
    bib = "@phdthesis{a, title={T}, school={MIT}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_phdthesis_without_school_is_reported():
    bib = "@phdthesis{a, title={T}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert ("bib.missing_required_field", "school") in [(f.rule, f.symbol) for f in out]


def test_populated_mastersthesis_school_is_not_reported():
    bib = "@mastersthesis{a, title={T}, school={MIT}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_mastersthesis_without_school_is_reported():
    bib = "@mastersthesis{a, title={T}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), bib)
    assert ("bib.missing_required_field", "school") in [(f.rule, f.symbol) for f in out]


def test_double_quoted_raw_only_field_value_is_recognized():
    bib = '@book{b, title={T}, publisher = "P", year={2020}, doi={10.1/x}}'
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_nested_braces_in_a_raw_only_field_value_is_recognized():
    bib = "@book{b, title={T}, publisher={A {B} C}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_empty_braces_on_a_raw_only_field_still_counts_as_missing():
    bib = "@book{b, title={T}, publisher={}, year={2020}, doi={10.1/x}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert ("bib.missing_required_field", "publisher") in [(f.rule, f.symbol) for f in out]


# --- raw-only field presence must be anchored to an actual field boundary ----------------------
# Fix round 2: the old `_RAW_ONLY_FIELD_RE` matched a field's NAME anywhere in the raw text
# followed by "=", including inside an unrelated field's own braced value. These pin the
# replacement (`_raw_top_level_fields`, a brace-depth-aware scan) against that exact defect
# class, in both directions: a word that merely looks like a field name must not count as one
# (false negative on the finding), and a comma inside a braced value must not be mistaken for a
# field separator either.


def test_field_name_inside_another_value_is_not_presence():
    # "school" appears inside title's own braces, immediately followed by "=" -- the old regex
    # matched that and treated "school" as present even though the entry has no school field.
    bib = "@phdthesis{t, title={On school = society}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{t}\n"}), bib)
    assert ("bib.missing_required_field", "school") in [(f.rule, f.symbol) for f in out]


def test_comma_inside_a_braced_value_does_not_create_a_field_boundary():
    # The comma inside title's braces must not be read as separating "school = b" into its own
    # top-level field.
    bib = "@phdthesis{t, title={a, school = b}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{t}\n"}), bib)
    assert ("bib.missing_required_field", "school") in [(f.rule, f.symbol) for f in out]


def test_real_top_level_field_after_a_braced_value_is_found():
    # A genuine school="S" field, reached only after a braced value (and the depth-0 comma that
    # follows it), must still be found.
    bib = "@phdthesis{t, title={a, b}, school={S}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{t}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_field_at_the_very_start_of_raw_is_found():
    bib = "@book{b, publisher={P}, title={T}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert "bib.missing_required_field" not in [f.rule for f in out]


def test_unbalanced_braces_do_not_hide_a_present_field():
    # This entry's title value opens a brace it never closes, so bibtexparser itself rejects the
    # whole block ("Unexpectedly reached end of file") rather than handing us a parsed entry --
    # verified by hand: parse_bib_entries("@book{b, title={unclosed {brace, ...") returns {}.
    # With no usable entries at all, check_bibliography takes the pre-existing "no bibliography
    # supplied" early exit (see the module docstring and test_no_bib_content_reports_nothing_
    # rather_than_everything above) before our brace-depth scan ever runs. So for *this specific*
    # flavor of malformed BibTeX, "a present field must not look absent" holds trivially: no
    # field of any entry is reported as either present or missing, because there is no entry.
    bib = "@book{b, title={unclosed {brace, publisher={P}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert out == []


def test_malformed_quoting_does_not_hide_a_present_field_via_the_fallback():
    # Unlike the test above, THIS malformed entry does parse: bibtexparser's own tokenizer
    # handles the stray "{" inside the quoted title value just fine (title, publisher, and year
    # all come back correctly in the parsed dict -- verified by hand). But that stray "{" is
    # invisible to our depth-unaware scan as a quote, so it reads as a real, never-closed open
    # brace: `_raw_top_level_fields` swallows "publisher={P}, year={2020}" into what it thinks is
    # still title's value, finds no top-level "publisher", and reports `balanced=False`. That
    # flag is exactly what sends `_field_is_present` to the unanchored fallback regex, which does
    # find "publisher={P}" in the raw text and correctly calls it present. This is the "fallback"
    # branch that test_unbalanced_braces_do_not_hide_a_present_field never reaches.
    bib = '@book{b, title="open { brace", publisher={P}, year={2020}}'
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert ("bib.missing_required_field", "publisher") not in [(f.rule, f.symbol) for f in out]


# --- collect_cite_keys ------------------------------------------------------------------------


def test_collect_cite_keys_reports_the_citing_file_and_line():
    src = build_source("main.tex", {"main.tex": "intro\n\\cite{a}\n"})
    keys = collect_cite_keys(src)
    assert keys["a"] == ("main.tex", 2)


def test_collect_cite_keys_keeps_the_first_occurrence_across_files():
    # iter_masked() yields each file whole, main file first, then includes in resolution order —
    # so a citation anywhere in main.tex wins over one in an include regardless of where \input
    # sits textually, and between two sibling includes the earlier \input wins.
    src = build_source(
        "main.tex",
        {
            "main.tex": "\\input{sec/one}\n\\input{sec/two}\n",
            "sec/one.tex": "\\cite{a}\n",
            "sec/two.tex": "\\cite{a}\n",
        },
    )
    keys = collect_cite_keys(src)
    assert keys["a"] == ("sec/one.tex", 1)


def test_collect_cite_keys_prefers_the_main_file_over_an_include():
    src = build_source(
        "main.tex",
        {"main.tex": "\\input{sec/one}\n\\cite{a}\n", "sec/one.tex": "\\cite{a}\n"},
    )
    keys = collect_cite_keys(src)
    assert keys["a"] == ("main.tex", 2)


def test_collect_cite_keys_unions_capitalized_and_lowercase_forms():
    src = build_source("main.tex", {"main.tex": "\\citep{a}\\Citep{b}\n"})
    assert set(collect_cite_keys(src)) == {"a", "b"}


def test_collect_cite_keys_ignores_commented_out_cites():
    src = build_source("main.tex", {"main.tex": "% \\cite{a}\n\\cite{b}\n"})
    assert set(collect_cite_keys(src)) == {"b"}
