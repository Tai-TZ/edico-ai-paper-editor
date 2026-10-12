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
    for text in (
        "Funded under VINIF.2020.DA15 project.",
        "Supported by FWF P 12345.",
        "FWF P12345",
        "NAFOSTED 103.99-2019.12",
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
    for text in (
        "ERC-2019-ADG",
        "ERC-2021-COG",
        "NRF-2021R1A2C1",
        "NSF-1234567",
        "DFG 123456",
        "Funded under VINIF.2020.DA15 project.",
        "Supported by FWF P 12345.",
        "NAFOSTED 103.99-2019.12",
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
    for text in (
        "NSF-1234567",
        "DFG 123456",
        "ERC-2019-ADG",
        "NRF-2021R1A2C1",
        "Funded under VINIF.2020.DA15 project.",
        "Supported by FWF P 12345.",
        "NAFOSTED 103.99-2019.12",
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
