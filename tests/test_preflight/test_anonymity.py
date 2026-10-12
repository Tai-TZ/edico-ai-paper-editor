"""``check_anonymity``: double-blind identity-leak rules (author/affiliation/email critical;
orcid/thanks/acknowledgements/funding warning; self-reference/repository-link info)."""

from __future__ import annotations

from src.services.preflight.rules.anonymity import check_anonymity
from src.services.preflight.source import build_source


def _a(doc):
    return [x.rule for x in check_anonymity(build_source("main.tex", {"main.tex": doc}))]


# --- brief's pinned tests, verbatim -------------------------------------------------------------


def test_a_real_author_is_critical():
    assert "anon.author_populated" in _a("\\author{Jane Doe}\n")


def test_an_anonymised_author_is_clean():
    assert _a("\\author{Anonymous Authors}\n") == []
    assert _a("\\author{}\n") == []


def test_email_and_orcid_are_caught():
    assert "anon.email_present" in _a("Contact a@b.edu\n")
    assert "anon.orcid_present" in _a("\\orcid{0000-0002-1825-0097}\n")


def test_acknowledgements_section_is_flagged_in_both_languages():
    assert "anon.acknowledgements_present" in _a("\\section{Acknowledgements}\nThanks.\n")
    assert "anon.acknowledgements_present" in _a("\\section{Lời cảm ơn}\nCảm ơn.\n")


def test_grant_number_is_flagged():
    assert "anon.funding_identifiers" in _a("Supported by NSF-1234567.\n")


def test_self_reference_phrase_is_info():
    assert "anon.self_reference" in _a("In our previous work we showed this.\n")


def test_a_commented_author_block_is_not_a_leak():
    assert _a("% \\author{Jane Doe}\n") == []


# --- extra: author_populated / affiliation_populated --------------------------------------------


def test_anonymised_author_singular_and_abbreviated_forms_are_clean():
    assert _a("\\author{Anonymous Author}\n") == []
    assert _a("\\author{Anon.}\n") == []


def test_a_venue_s_own_anonymising_macro_is_not_a_leak():
    # A value that is nothing but LaTeX commands (no visible text at all) must be treated as
    # anonymised -- a false critical here is the worst outcome in the whole feature.
    assert _a("\\author{\\anonymousauthors}\n") == []


def test_real_affiliation_is_critical_but_placeholder_is_clean():
    assert "anon.affiliation_populated" in _a("\\affiliation{MIT}\n")
    assert "anon.affiliation_populated" in _a("\\institute{Stanford University}\n")
    out = _a("\\affiliation{Anonymous}\n")
    assert "anon.affiliation_populated" not in out


def test_author_with_nested_thanks_command_still_counts_as_populated():
    out = _a("\\author{Jane Doe\\thanks{Equal contribution}}\n")
    assert "anon.author_populated" in out


def test_multi_author_and_is_a_single_populated_finding():
    out = check_anonymity(build_source("main.tex", {"main.tex": "\\author{Jane Doe \\and John Smith}\n"}))
    hits = [f for f in out if f.rule == "anon.author_populated"]
    assert len(hits) == 1
    assert hits[0].symbol == "Jane Doe John Smith"


# --- extra: email ---------------------------------------------------------------------------


def test_doi_is_not_an_email():
    assert "anon.email_present" not in _a("See doi: 10.1145/3292500.3330701\n")


def test_cite_key_with_at_sign_is_not_an_email():
    assert "anon.email_present" not in _a("\\cite{smith@2020}\n")


def test_escaped_at_and_mailto_url_are_both_caught():
    assert "anon.email_present" in _a("Contact: name\\@example.com\n")
    assert "anon.email_present" in _a("\\url{mailto:jane@example.com}\n")


def test_multiple_emails_aggregate_into_one_finding_with_a_count():
    out = check_anonymity(build_source("main.tex", {"main.tex": "Email a@b.edu or backup c@d.org.\n"}))
    hits = [f for f in out if f.rule == "anon.email_present"]
    assert len(hits) == 1
    assert hits[0].count == 2
    assert hits[0].symbol == "a@b.edu"


# --- extra: orcid / thanks --------------------------------------------------------------------


def test_bare_orcid_id_without_the_command_is_caught():
    assert "anon.orcid_present" in _a("ORCID: 0000-0002-1825-0097\n")


def test_thanks_footnote_is_flagged():
    out = _a("\\author{Jane Doe\\thanks{Corresponding author: jane@example.com}}\n")
    assert "anon.thanks_present" in out


def test_commented_out_orcid_and_thanks_are_not_findings():
    doc = "% \\orcid{0000-0002-1825-0097}\n% \\thanks{Jane Doe}\n"
    out = _a(doc)
    assert "anon.orcid_present" not in out
    assert "anon.thanks_present" not in out


# --- extra: acknowledgements ------------------------------------------------------------------


def test_acknowledgements_environment_is_flagged():
    doc = "\\begin{acknowledgements}\nThanks to our funders.\n\\end{acknowledgements}\n"
    assert "anon.acknowledgements_present" in _a(doc)


def test_american_spelling_without_the_e_is_flagged():
    assert "anon.acknowledgements_present" in _a("\\section*{Acknowledgments}\nThanks.\n")


def test_no_acknowledgements_heading_is_clean():
    assert "anon.acknowledgements_present" not in _a("\\section{Introduction}\nText.\n")


# --- extra: funding identifiers ----------------------------------------------------------------


def test_bare_four_digit_year_does_not_fire_funding_identifiers():
    assert "anon.funding_identifiers" not in _a("In 2024, we conducted a large-scale study.\n")


def test_dfg_and_erc_grant_shapes_are_recognised():
    assert "anon.funding_identifiers" in _a("Funded in part by DFG 123456.\n")
    assert "anon.funding_identifiers" in _a("This work was funded by ERC-2019-ADG.\n")


def test_explicit_grant_number_phrases_are_recognised():
    assert "anon.funding_identifiers" in _a("This research was supported under Grant No. 12345.\n")
    assert "anon.funding_identifiers" in _a("Funded by grant number 98765.\n")
    assert "anon.funding_identifiers" in _a("Work carried out under grant 55555.\n")


def test_vietnamese_grant_phrases_accented_and_unaccented_are_recognised():
    assert "anon.funding_identifiers" in _a("Đề tài có mã số đề tài B2024-01.\n")
    assert "anon.funding_identifiers" in _a("De tai co ma so de tai B2024-01.\n")


def test_unrelated_acronym_and_number_is_not_a_grant():
    # "GPT-4" has the same shape (letters, hyphen, digit) as a grant id but is not one -- the
    # agency list is deliberately closed rather than "any short uppercase word + digit".
    assert "anon.funding_identifiers" not in _a("We evaluate GPT-4 on this benchmark.\n")


# --- extra: self reference --------------------------------------------------------------------


def test_bare_our_work_and_we_show_do_not_fire_self_reference():
    doc = "Our work shows strong results. We show the following lemma holds.\n"
    assert "anon.self_reference" not in _a(doc)


def test_vietnamese_self_reference_is_recognised():
    assert "anon.self_reference" in _a("Đây là nghiên cứu trước của chúng tôi về chủ đề này.\n")
    assert "anon.self_reference" in _a("Day la nghien cuu truoc cua chung toi ve chu de nay.\n")


def test_we_previously_showed_is_recognised():
    assert "anon.self_reference" in _a("We previously demonstrated this result in a workshop paper.\n")


# --- extra: repository link -------------------------------------------------------------------


def test_personal_repository_link_is_flagged():
    assert "anon.repository_link" in _a("Code is available at https://github.com/janedoe/my-project.\n")


def test_bare_github_com_with_no_path_is_not_a_finding():
    assert "anon.repository_link" not in _a("We used github.com to host our development tools.\n")


def test_well_known_org_repository_is_not_flagged():
    assert "anon.repository_link" not in _a("Built on top of github.com/pytorch/pytorch.\n")


def test_gitlab_personal_namespace_is_also_flagged():
    assert "anon.repository_link" in _a("See gitlab.com/janedoe/experiments for our code.\n")


# --- extra: findings carry a line and a symbol --------------------------------------------------


def test_placeholder_author_with_a_trailing_linebreak_is_not_a_leak():
    for value in (
        "Anonymous\\\\",
        "Anonymous Authors \\\\",
        "Anonymous\\\\[2ex]",
        "Anonymous\\\\*",
        "Anonymous\\newline",
    ):
        doc = f"\\author{{{value}}}\n"
        assert check_anonymity(build_source("main.tex", {"main.tex": doc})) == [], value


def test_placeholder_affiliation_with_a_trailing_linebreak_is_not_a_leak():
    doc = "\\institute{Anonymous\\\\}\n"
    assert check_anonymity(build_source("main.tex", {"main.tex": doc})) == []


def test_a_real_name_with_a_trailing_linebreak_still_leaks():
    doc = "\\author{Jane Doe\\\\}\n"
    out = check_anonymity(build_source("main.tex", {"main.tex": doc}))
    assert "anon.author_populated" in [f.rule for f in out]


def test_linebreak_separated_name_and_affiliation_both_appear_in_the_symbol():
    doc = "\\author{Jane Doe\\\\MIT}\n"
    out = [f for f in check_anonymity(build_source("main.tex", {"main.tex": doc})) if f.rule == "anon.author_populated"]
    assert "Jane Doe" in out[0].symbol and "MIT" in out[0].symbol


def test_vietnamese_and_european_funder_codes_are_recognised():
    # Updated in fix round 5: "FWF P12345" and "NAFOSTED 103.99-2019.12" used to be asserted bare.
    # The bare agency-prefix path now requires a funding-context word in the same sentence, so the
    # inputs carry one -- the grant-code SHAPES under test (the dot separator, the one-letter
    # grant-type code, the decimal-bearing NAFOSTED form) are unchanged.
    for text in (
        "Funded under VINIF.2020.DA15 project.",
        "Supported by FWF P 12345.",
        "Supported by FWF P12345.",
        "Funded by NAFOSTED 103.99-2019.12.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


def test_product_names_and_standards_are_not_grant_numbers():
    for text in (
        "We used GPT-4 for this.",
        "Compliant with ISO-9001.",
        "In 2024 we ran the study.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" not in [f.rule for f in out], text


def test_common_scientific_tokens_are_not_grant_numbers():
    for text in (
        "We used the MRC-5 cell line for this experiment.",
        "The ARC-1234 connector was used.",
        "Samples were stored in the VAST-2 archive.",
        "We used GPT-4 for this.",
        "Compliant with ISO-9001.",
        "In 2024 we ran the study.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" not in [f.rule for f in out], text


def test_removed_agencies_are_still_caught_through_the_grant_phrase_path():
    for text in (
        "Funded by the MRC under grant 12345.",
        "Supported by the ARC, grant no. DP123456.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


def test_token_standards_are_not_grant_numbers():
    for text in (
        "We implement an ERC-20 token.",
        "The ERC-721 standard applies.",
        "An ERC-1155 multi-token contract.",
        "The NRF-2 pathway was studied.",
        "The Nrf2 pathway was studied.",
        "NRF2 activation was measured.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" not in [f.rule for f in out], text


def test_real_grant_codes_still_fire():
    # Updated in fix round 5: the four bare agency forms gained the funding word the new
    # same-sentence requirement needs. The two ERC forms stay BARE deliberately -- _ERC_GRANT_RE
    # is exempt from that requirement (its call-year-plus-uppercase-programme shape is its own
    # second piece of evidence), and this test is what pins that exemption.
    for text in (
        "ERC-2019-ADG",
        "ERC-2021-COG",
        "Supported by NRF-2021R1A2C1.",
        "Supported by NSF-1234567.",
        "Funded by DFG 123456.",
        "Funded under VINIF.2020.DA15 project.",
        "Supported by FWF P 12345.",
        "We acknowledge NAFOSTED 103.99-2019.12.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


def test_metric_thresholds_are_not_grant_numbers():
    for text in (
        "The FNR 0.05 threshold was used.",
        "FNR-0.95 is the achieved operating point.",
        "We report FPR 0.01 and TPR 0.99.",
        "The NSF 0.05 significance level was applied.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" not in [f.rule for f in out], text


def test_real_grant_codes_survive_the_decimal_guard():
    # Updated in fix round 5, same reason as test_real_grant_codes_still_fire: the bare agency
    # forms gained a funding word; "ERC-2019-ADG" stays bare (exempt path); the FNR line already
    # went through the grant-phrase path, which is untouched.
    for text in (
        "Supported by NSF-1234567.",
        "Funded by DFG 123456.",
        "ERC-2019-ADG",
        "Supported by NRF-2021R1A2C1.",
        "Funded under VINIF.2020.DA15 project.",
        "Supported by FWF P 12345.",
        "We acknowledge NAFOSTED 103.99-2019.12.",
        "Funded by the FNR under grant 12345.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


def test_author_finding_reports_file_line_and_symbol():
    out = check_anonymity(build_source("main.tex", {"main.tex": "Intro.\n\\author{Jane Doe}\n"}))
    hit = next(f for f in out if f.rule == "anon.author_populated")
    assert hit.file == "main.tex"
    assert hit.line == 2
    assert hit.symbol == "Jane Doe"


def test_identity_in_an_input_ed_appendix_is_still_a_leak():
    files = {"main.tex": "\\input{appendix}\n", "appendix.tex": "\\author{Jane Doe}\n"}
    out = check_anonymity(build_source("main.tex", files))
    hit = next(f for f in out if f.rule == "anon.author_populated")
    assert hit.file == "appendix.tex"


# --- fix round 5: the bare agency-prefix path needs a funding word in the same sentence --------


def test_technical_identifiers_near_agency_names_are_not_grants():
    for text in (
        "Simulated in DOE-2.1E.",
        "The NASA-STD-3001 limits apply.",
        "Per DOE-STD-1020 the design holds.",
        "See the NSF TR 1234 report.",
        "Cells were NIH-3T3 fibroblasts.",
        "The NRF-2 pathway was studied.",
        "Certified to NSF 61 for potable water.",
        "We used the NASA-TLX workload scale.",
        "The kinase adopts a DFG-in conformation.",
        "The FNR 0.05 threshold was used.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" not in [f.rule for f in out], text


def test_funding_sentences_still_fire():
    for text in (
        "This work was supported by NSF-1234567.",
        "Funded by DFG 123456.",
        "The authors are grateful for support from ERC-2019-ADG.",
        "This research was funded under VINIF.2020.DA15.",
        "Supported by FWF P 12345.",
        "We acknowledge NAFOSTED 103.99-2019.12.",
        "Nghiên cứu được tài trợ bởi NAFOSTED 103.99-2019.12.",
        "Nghien cuu duoc tai tro boi NAFOSTED 103.99-2019.12.",
        "Funded by the FNR under grant 12345.",
        "Supported by the ARC, grant no. DP123456.",
        "under Grant No. 12345",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


def test_a_funding_word_in_a_neighbouring_sentence_does_not_count():
    doc = "This work was supported generously. Cells were NIH-3T3 fibroblasts.\n"
    out = check_anonymity(build_source("main.tex", {"main.tex": doc}))
    assert "anon.funding_identifiers" not in [f.rule for f in out]


def test_the_sentence_boundary_holds_for_a_code_that_clears_the_floor():
    # The pinned neighbouring-sentence test above uses NIH-3T3, whose code is 3 characters and so
    # is already stopped by round 3's floor -- it would pass even with a raw character window.
    # These inputs use codes that DO clear the floor and the decimal guard, so the sentence
    # boundary is the only thing keeping them quiet, in both scan directions.
    for doc in (
        "The grant was generous. Simulated in DOE-2.1E.\n",
        "Simulated in DOE-2.1E. The grant was generous.\n",
        "Simulated in DOE-2.1E! Funded elsewhere.\n",
        "Simulated in DOE-2.1E? Funded elsewhere.\n",
        "Funded generously.\n\nSimulated in DOE-2.1E and reported.\n",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": doc}))
        assert "anon.funding_identifiers" not in [f.rule for f in out], doc


def test_a_funding_word_after_the_code_in_the_same_sentence_counts():
    # The scan runs outward in BOTH directions from the match, not only leftward: a funding word
    # trailing the code is the same evidence as one preceding it.
    for text in (
        "This project (NSF-1234567) was supported in full.",
        "Work on DFG 123456 was financed by the project.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


def test_a_bare_agency_code_with_no_funding_word_is_deliberately_silent():
    # The accepted trade-off of the fix-round-5 requirement, pinned so nobody "fixes" it back: a
    # lone agency code in a sentence with no funding vocabulary is now silent on the agency path.
    # The explicit grant-phrase path still catches the same number independently.
    out = check_anonymity(build_source("main.tex", {"main.tex": "NSF-1234567.\n"}))
    assert "anon.funding_identifiers" not in [f.rule for f in out]
    out = check_anonymity(build_source("main.tex", {"main.tex": "Grant No. NSF-1234567.\n"}))
    assert "anon.funding_identifiers" in [f.rule for f in out]


def test_erc_path_stays_exempt_from_the_context_requirement():
    # Both halves of the exemption: a bare real ERC code fires with no funding word anywhere, and
    # a token-standard name stays silent even when the sentence is full of funding vocabulary.
    out = check_anonymity(build_source("main.tex", {"main.tex": "ERC-2018-STG\n"}))
    assert "anon.funding_identifiers" in [f.rule for f in out]
    for text in (
        "The supported contract uses an ERC-20 token.",
        "Our funded prototype implements ERC-1155 multi-token transfers.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" not in [f.rule for f in out], text


def test_vietnamese_funding_context_words_are_accepted_accented_and_unaccented():
    for text in (
        "Kinh phí cho nghiên cứu này đến từ NAFOSTED 103.99-2019.12.",
        "Kinh phi cho nghien cuu nay den tu NAFOSTED 103.99-2019.12.",
        "Hỗ trợ bởi NSF-1234567.",
        "Ho tro boi NSF-1234567.",
        "Học bổng NSF-1234567.",
        "Hoc bong NSF-1234567.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


def test_thanks_counts_as_funding_context():
    for text in (
        "We thank the NSF (NSF-1234567).",
        "The authors thank NAFOSTED 103.99-2019.12.",
        "We thank the National Science Foundation, NSF-1234567.",
        "Cảm ơn NAFOSTED 103.99-2019.12.",
        "Cam on NAFOSTED 103.99-2019.12.",
    ):
        out = check_anonymity(build_source("main.tex", {"main.tex": text + "\n"}))
        assert "anon.funding_identifiers" in [f.rule for f in out], text


# --- final whole-branch review, FIX 1: real venue templates must never fire a false critical ----

# (\author{...} content, where it comes from). Every row is verbatim template content an author is
# INSTRUCTED to leave untouched when they submit, or a placeholder this product ships itself -- so
# a finding on any of them is a `critical` on a correct document, which spec §7 names as the
# failure that destroys trust in the whole panel. The venue name travels into the assertion
# message so a future regression says which template broke.
_ANONYMISED_AUTHOR_BLOCKS = (
    ("Author Name", "this repo's default new paper (frontend/src/lib/project-store.ts)"),
    ("Tên tác giả", "this repo's VI default (frontend/src/lib/project-store.ts)"),
    ("Ten tac gia", "this repo's VI default, unaccented spelling"),
    ("First Author\\inst{1} \\and Second Author\\inst{2}", "this repo's Springer seed (template_builtins.py)"),
    ("Anonymous Author(s) \\\\ Affiliation \\\\ Address \\\\ \\texttt{email@domain}", "ICLR"),
    ("Anonymous ACL submission", "ACL/EMNLP"),
    ("Anonymous CVPR submission\\\\ Paper ID \\cvprPaperID", "CVPR"),
    ("Anonymous Submission", "AAAI"),
    ("Author Withheld", "generic withheld"),
    ("[Redacted for double-blind review]", "generic redacted"),
    ("Removed for review", "generic removed-for-review"),
    ("\\anonymousauthors", "a venue's own anonymising macro: markup with no visible text"),
)

# The other direction: a value that is a real identity must still be critical. A fix that silences
# a true leak is far worse than the false-positive bug it was written to close.
_LEAKING_AUTHOR_BLOCKS = (
    ("Jane Doe", "a bare real name"),
    ("Jane Doe \\and John Smith", "two real names"),
    ("Jane Doe\\\\MIT", "a real name and an affiliation on two lines"),
    ("\\textbf{Jane Doe}", "a real name wrapped in markup"),
)


def test_no_major_venue_s_unmodified_anonymous_template_fires_a_critical():
    for value, venue in _ANONYMISED_AUTHOR_BLOCKS:
        doc = f"\\author{{{value}}}\n"
        assert check_anonymity(build_source("main.tex", {"main.tex": doc})) == [], f"{venue}: {value!r}"


def test_the_same_anonymised_values_are_also_clean_in_an_affiliation_command():
    for value, venue in _ANONYMISED_AUTHOR_BLOCKS:
        doc = f"\\institute{{{value}}}\n"
        assert check_anonymity(build_source("main.tex", {"main.tex": doc})) == [], f"{venue}: {value!r}"


def test_a_real_identity_still_fires_critical_in_both_commands():
    for value, shape in _LEAKING_AUTHOR_BLOCKS:
        author = f"\\author{{{value}}}\n"
        assert "anon.author_populated" in _a(author), f"author, {shape}: {value!r}"
        affiliation = f"\\institute{{{value}}}\n"
        assert "anon.affiliation_populated" in _a(affiliation), f"institute, {shape}: {value!r}"


def test_a_real_institution_name_is_not_mistaken_for_an_anonymised_value():
    for value in ("MIT", "Stanford University", "Đại học Quốc gia Hà Nội", "Hanoi University of Science"):
        doc = f"\\affiliation{{{value}}}\n"
        assert "anon.affiliation_populated" in _a(doc), value
