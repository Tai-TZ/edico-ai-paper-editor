"""Required-statement rules for Submission Preflight.

Journals desk-reject for a missing data-availability, ethics/IRB, conflict-of-interest, funding,
or author-contributions disclosure. The author usually wrote the statement; the risk is that this
checker fails to recognise where they put it. A statement counts as present the moment EITHER of
two independent signals appears anywhere across the whole source (``src.iter_masked()`` — a
statement in an included back-matter file counts same as one in the main file):

- a **heading**: ``\\section{Data Availability}``, ``\\section*{...}``, ``\\subsection{...}``,
  ``\\paragraph{...}``, or a named ``\\begin{...}`` environment (e.g. ``\\begin{acknowledgements}``).
- an **inline phrase** anywhere in the body (``"available upon request"``, ``"the authors declare
  no competing interests"``).

Matching is case-insensitive and covers English and Vietnamese, accented and unaccented, per this
product's bilingual audience — the same convention as the alias table in ``parse_latex_sections``
(``src/services/parser/latex.py``'s ``find_section_for_query``, which carries both ``"tóm tắt"``
and ``"tom tat"``).

This rule leans toward recognising a statement: a false "missing" (the statement is there but
unrecognised) is the costly error — it reads as an insult to an author who did the work. A false
"present" (the statement is truly absent but something adjacent fooled the matcher) is the
cheaper mistake, so most terms here are deliberately broad. The one deliberate exception is
``ethics``: see the comment on ``_ETHICS_HEADING_ONLY_TERMS`` below for why the bare word is
accepted in a heading but not in body prose.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from src.services.preflight.catalogue import Finding
from src.services.preflight.source import PreflightSource


def _heading(terms: str, envs: str = "") -> re.Pattern[str]:
    """A sectioning command (``\\section``/``\\subsection``/``\\subsubsection``/``\\paragraph``,
    optionally starred) whose title contains ``terms``, or a ``\\begin{<env>}`` opener naming one
    of ``envs``. ``[^}]*`` lets the brace-content match include nested formatting commands (e.g.
    ``\\section{\\textbf{Data Availability}}``); the regex backtracks past the inner ``{`` to find
    ``terms`` before the next literal ``}``.
    """
    pattern = r"\\(?:(?:sub){0,2}section|paragraph)\*?\s*\{[^}]*(?:" + terms + r")[^}]*\}"
    if envs:
        pattern += r"|\\begin\{\s*(?:" + envs + r")\s*\}"
    return re.compile(pattern, re.IGNORECASE)


def _phrase(terms: str) -> re.Pattern[str]:
    """``terms`` searched anywhere in the body, no heading required."""
    return re.compile(terms, re.IGNORECASE)


# A bounded "nearby" gap for phrase patterns that pair two terms loosely (e.g. "available ...
# request") without the pairing crossing a sentence boundary. Excludes periods, so it can shrink
# to fit between two words in the same sentence but can never stretch past a "." into the next
# one — "available." followed by an unrelated "request" one sentence later must not pair up.
_NEARBY_GAP = r"[^.]{0,80}?"


# --- data_availability ---------------------------------------------------------------------
# EN: data availability / data availability statement / availability of data / data sharing.
# VI: "tính khả dụng (của) dữ liệu", "chia sẻ dữ liệu" + unaccented. Kept broad — see module
# docstring.
_DATA_AVAILABILITY_TERMS = (
    r"\bdata\s+availability(?:\s+statement)?\b"
    r"|\bavailability\s+of\s+data\b"
    r"|\bdata\s+sharing(?:\s+statement)?\b"
    r"|\btính\s+khả\s+dụng(?:\s+của)?\s+dữ\s+liệu\b"
    r"|\btinh\s+kha\s+dung(?:\s+cua)?\s+du\s+lieu\b"
    r"|\bchia\s+sẻ\s+dữ\s+liệu\b"
    r"|\bchia\s+se\s+du\s+lieu\b"
)
# Inline-only phrasing: a disclosure sentence with no dedicated heading at all. "available" is
# paired with its tail term through the bounded _NEARBY_GAP rather than a fixed "upon|on" — the
# single most common real-world wording is "available from the corresponding author on
# reasonable request" (fix round 1, IMPORTANT 1), and the gap also lets this family absorb the
# Science/PNAS-style "available in the main text or the supplementary materials" (IMPORTANT 2).
# "data are/is available" and the Vietnamese "có sẵn"/"co san" pairings are the same shape.
_DATA_AVAILABILITY_PHRASE_EXTRA = (
    r"|\bdata\s+supporting\s+the\s+findings\b"
    r"|\bavailable\b"
    + _NEARBY_GAP
    + r"\b(?:request|corresponding\s+author|main\s+text|supplementary\s+materials?|supplementary\s+information)\b"
    r"|\bdata\s+(?:are|is)\s+available\b"
    r"|\bcó\s+sẵn\b" + _NEARBY_GAP + r"\b(?:yêu\s+cầu|tác\s+giả\s+liên\s+hệ|văn\s+bản\s+chính|tài\s+liệu\s+bổ\s+sung)\b"
    r"|\bco\s+san\b" + _NEARBY_GAP + r"\b(?:yeu\s+cau|tac\s+gia\s+lien\s+he|van\s+ban\s+chinh|tai\s+lieu\s+bo\s+sung)\b"
    r"|\bdữ\s+liệu\s+có\s+sẵn\b"
    r"|\bdu\s+lieu\s+co\s+san\b"
)
_DATA_AVAILABILITY_HEADING_RE = _heading(_DATA_AVAILABILITY_TERMS, envs=r"data[-_]?availability|datasharing")
_DATA_AVAILABILITY_PHRASE_RE = _phrase(_DATA_AVAILABILITY_TERMS + _DATA_AVAILABILITY_PHRASE_EXTRA)

# --- ethics ----------------------------------------------------------------------------------
# EN: ethics / ethical approval / IRB / institutional review board / informed consent / ethics
# committee. VI: "đạo đức (nghiên cứu)", "chấp thuận đạo đức" + unaccented.
#
# Narrowed deliberately: the bare noun ("Ethics", "Đạo đức") is accepted ONLY as a heading. A
# dedicated section titled exactly "Ethics" is an unambiguous, deliberate disclosure signal — no
# author titles a general-topic discussion section bare "Ethics" in a submission. The same bare
# word is excluded from the phrase table, because a paper *about* research ethics as its subject
# will use "ethical"/"ethics" constantly in ordinary prose without ever disclosing an approval;
# crediting that paper with a disclosure it never made is exactly the false "present" this module
# must not produce for a topic word. Phrase matching instead requires a compound ("ethical
# approval", "ethics committee", "IRB", ...) that only appears in an actual disclosure sentence.
_ETHICS_HEADING_ONLY_TERMS = (
    r"\bethics(?:\s+(?:statement|declaration|committee|approval|clearance|review))?\b"
    r"|\bđạo\s+đức(?:\s+nghiên\s+cứu)?\b"
    r"|\bdao\s+duc(?:\s+nghien\s+cuu)?\b"
)
_ETHICS_PHRASE_TERMS = (
    r"\bethical\s+approval\b"
    r"|\bethics\s+approval\b"
    r"|\bethics\s+committee\b"
    r"|\binstitutional\s+review\s+board\b"
    r"|\bIRB\b"
    r"|\binformed\s+consent\b"
    r"|\bchấp\s+thuận\s+đạo\s+đức\b"
    r"|\bchap\s+thuan\s+dao\s+duc\b"
)
_ETHICS_HEADING_RE = _heading(
    _ETHICS_HEADING_ONLY_TERMS + "|" + _ETHICS_PHRASE_TERMS,
    envs=r"ethicsstatement|ethicsdeclaration|ethicalapproval",
)
_ETHICS_PHRASE_RE = _phrase(_ETHICS_PHRASE_TERMS)

# --- coi (conflict of interest) ----------------------------------------------------------------
# EN: conflict(s) of interest / competing interests / declaration of interest / "the authors
# declare no". VI: "xung đột lợi ích", "lợi ích cạnh tranh" + unaccented. All compounds already,
# so none need narrowing — a bare "interest" alone is not in this list.
_COI_TERMS = (
    r"\bconflicts?\s+of\s+interest\b"
    r"|\bcompeting\s+(?:financial\s+|non-financial\s+)?interests?\b"
    r"|\bdeclaration\s+of\s+interests?\b"
    r"|\bthe\s+authors?\s+declare\s+no\b"
    r"|\bxung\s+đột\s+lợi\s+ích\b"
    r"|\bxung\s+dot\s+loi\s+ich\b"
    r"|\blợi\s+ích\s+cạnh\s+tranh\b"
    r"|\bloi\s+ich\s+canh\s+tranh\b"
)
_COI_HEADING_RE = _heading(_COI_TERMS, envs=r"conflictofinterest|conflictsofinterest|competinginterests")
_COI_PHRASE_RE = _phrase(_COI_TERMS)

# --- funding -------------------------------------------------------------------------------
# EN: funding / funded by / financial support / grant / supported by. VI: "tài trợ", "kinh phí",
# "hỗ trợ tài chính" + unaccented. Kept deliberately broad, "grant" included: it will also match
# a sentence like "we are grateful for the grant of access to the dataset", which is a false
# "present" rather than a false "missing" — the cheaper mistake per the module docstring. The
# \begin{acknowledgements} environment is also accepted as a heading signal, on the same
# reasoning: funding disclosures conventionally live in the Acknowledgements section.
_FUNDING_TERMS = (
    r"\bfunding(?:\s+(?:statement|declaration|source|information))?\b"
    r"|\bfunded\s+by\b"
    r"|\bfinancial\s+support\b"
    r"|\bgrants?\b"
    r"|\bsupported\s+by\b"
    r"|\btài\s+trợ\b"
    r"|\btai\s+tro\b"
    r"|\bkinh\s+phí\b"
    r"|\bkinh\s+phi\b"
    r"|\bhỗ\s+trợ\s+tài\s+chính\b"
    r"|\bho\s+tro\s+tai\s+chinh\b"
)
# Heading-only, symmetric with the \begin{acknowledgements} environment above but for the
# Vietnamese heading form a Vietnamese paper actually uses: \section{Lời cảm ơn} ("Acknowledgements")
# is a \section title, not an environment, so it belongs in the heading terms, not in `envs`.
# Excluded from the phrase table on purpose — same treatment as "acknowledgements" itself, which
# is also heading/env-only and not a member of _FUNDING_TERMS.
_FUNDING_HEADING_ONLY_TERMS = r"\blời\s+cảm\s+ơn\b|\bloi\s+cam\s+on\b"
_FUNDING_HEADING_RE = _heading(
    _FUNDING_TERMS + "|" + _FUNDING_HEADING_ONLY_TERMS,
    envs=r"acknowledgements?|acknowledgments?|funding",
)
_FUNDING_PHRASE_RE = _phrase(_FUNDING_TERMS)

# --- author_contributions -------------------------------------------------------------------
# EN: author contributions / contributions of the authors / CRediT. VI: "đóng góp của tác giả",
# "đóng góp tác giả" + unaccented.
_AUTHOR_CONTRIBUTIONS_TERMS = (
    r"\bauthor\s+contributions?\b"
    r"|\bcontributions?\s+of\s+the\s+authors?\b"
    r"|\bCRediT\b"
    r"|\bđóng\s+góp\s+của\s+tác\s+giả\b"
    r"|\bdong\s+gop\s+cua\s+tac\s+gia\b"
    r"|\bđóng\s+góp\s+tác\s+giả\b"
    r"|\bdong\s+gop\s+tac\s+gia\b"
)
_AUTHOR_CONTRIBUTIONS_HEADING_RE = _heading(_AUTHOR_CONTRIBUTIONS_TERMS, envs=r"authorcontributions|credit")
_AUTHOR_CONTRIBUTIONS_PHRASE_RE = _phrase(_AUTHOR_CONTRIBUTIONS_TERMS)

# IMPORTANT 3 (fix round 1): a heading-less CRediT-style role list — "Conceptualization, A.B.;
# methodology, C.D." — never says the words "author contributions" or "CRediT" at all, so neither
# pattern above ever sees it. It has to be recognised by its SHAPE: a CRediT taxonomy role
# immediately followed by a comma/colon and an initials-or-name attribution, chained to at least
# one more such role+attribution segment by a semicolon.
#
# The trap this has to dodge: half the CRediT taxonomy (Methodology, Software, Resources,
# Validation, Investigation, Supervision, Visualization) are ALSO ordinary section titles.
# Matching a bare role word would make `\section{Methodology}` satisfy author_contributions on
# nearly every paper in existence — that single-word approach is rejected on purpose. The
# role-then-attribution shape defuses the trap structurally, not by keyword luck: a bare
# `\section{Methodology}` is followed by `}`, never by ", A.B.", and is never itself chained to a
# second role by a semicolon — so `\section{Methodology}` + `\section{Resources}` as two ordinary
# sections can never match this pattern, no matter how many CRediT-named sections a paper happens
# to have (test_ordinary_methodology_and_resources_sections_do_not_satisfy_contributions).
# Distinctness of the two roles is checked in Python after the regex match, not by the regex
# itself, so a real list repeating one role across contributors ("Methodology, A.B.; Methodology,
# C.D.") is treated the same as a trivial one-role repeat would be — rejected — while a genuine
# two-role list ("Conceptualization, A.B.; methodology, C.D.") is accepted, which is the one
# distinction that actually separates a contributions block from noise.
_CREDIT_ROLES = (
    r"conceptuali[sz]ation"
    r"|methodology"
    r"|software"
    r"|validation"
    r"|formal\s+analysis"
    r"|investigation"
    r"|resources"
    r"|data\s+curation"
    r"|writing\s*[-–—]?\s*original\s+draft"
    r"|writing\s*[-–—]?\s*review\s*(?:&|and)\s*editing"
    r"|visuali[sz]ation"
    r"|supervision"
    r"|project\s+administration"
    r"|funding\s+acquisition"
)
# The attribution right after the role: initials with periods ("A.B.", "J. D.") or a
# two-or-more-word capitalised name ("John Doe"). Requiring at least two words for the name form
# (not one) stops an ordinary Title-Case word from being mistaken for an attribution — a single
# capitalised word straight after "role," is far more likely to be another role or a stray heading
# than a surname.
_CREDIT_WHO = r"(?:(?:[A-Z]\.\s*){1,4}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})"
_CREDIT_SEGMENT = rf"\b(?:{_CREDIT_ROLES})\b\s*[:,]\s*{_CREDIT_WHO}"
_CREDIT_CHAIN_RE = re.compile(rf"{_CREDIT_SEGMENT}(?:\s*;\s*{_CREDIT_SEGMENT})+", re.IGNORECASE)
_CREDIT_ROLE_RE = re.compile(rf"\b(?:{_CREDIT_ROLES})\b", re.IGNORECASE)


def _credit_role_list_present(masked: str) -> bool:
    """True if ``masked`` contains a chained role-then-attribution list naming at least two
    DISTINCT CRediT roles (see the comment on ``_CREDIT_ROLES`` above for why "distinct" and
    "chained" are both load-bearing, not just "any role word appears somewhere")."""
    for match in _CREDIT_CHAIN_RE.finditer(masked):
        roles = {role.lower() for role in _CREDIT_ROLE_RE.findall(match.group(0))}
        if len(roles) >= 2:
            return True
    return False


# statement name -> an extra structural check beyond heading/phrase matching, for a statement
# whose disclosure shape is not a fixed heading or phrase at all. Checked only when both the
# heading and phrase patterns for that statement miss.
_EXTRA_CHECKS: dict[str, Callable[[str], bool]] = {
    "author_contributions": _credit_role_list_present,
}

# statement name -> heading pattern. Satisfied by a dedicated heading or named environment.
_HEADING_PATTERNS: dict[str, re.Pattern[str]] = {
    "data_availability": _DATA_AVAILABILITY_HEADING_RE,
    "ethics": _ETHICS_HEADING_RE,
    "coi": _COI_HEADING_RE,
    "funding": _FUNDING_HEADING_RE,
    "author_contributions": _AUTHOR_CONTRIBUTIONS_HEADING_RE,
}

# statement name -> body-phrase pattern. Satisfied by the phrase appearing anywhere, no heading
# required.
_PHRASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "data_availability": _DATA_AVAILABILITY_PHRASE_RE,
    "ethics": _ETHICS_PHRASE_RE,
    "coi": _COI_PHRASE_RE,
    "funding": _FUNDING_PHRASE_RE,
    "author_contributions": _AUTHOR_CONTRIBUTIONS_PHRASE_RE,
}


def check_statements(src: PreflightSource, required: Sequence[str]) -> list[Finding]:
    """One ``statement.<name>_missing`` finding per name in ``required`` that is absent everywhere.

    Only names in ``required`` are ever checked — the caller (a Pydantic ``Literal`` in practice)
    decides what is required, this module never invents a requirement. A name not recognised here
    is ignored silently rather than raising: it cannot really happen given the caller's type, and
    crashing a whole preflight run over an unknown statement name would be worse than skipping it.

    A statement is satisfied the moment its heading pattern, its phrase pattern, or (for
    ``author_contributions`` only) its extra structural check matches anywhere across
    ``src.iter_masked()`` — one matching file is enough, so a statement living in an included
    back-matter file counts the same as one in the main file.

    A finding for a missing statement has no meaningful location: there is no line to jump to for
    something that was never written. ``file`` is the main file, ``line`` stays ``None``, and the
    statement name goes in ``symbol``.
    """
    known = {name for name in required if name in _HEADING_PATTERNS}
    satisfied: set[str] = set()
    for _path, masked in src.iter_masked():
        remaining = known - satisfied
        if not remaining:
            break
        for name in remaining:
            if _HEADING_PATTERNS[name].search(masked) or _PHRASE_PATTERNS[name].search(masked):
                satisfied.add(name)
            elif name in _EXTRA_CHECKS and _EXTRA_CHECKS[name](masked):
                satisfied.add(name)

    return [
        Finding(rule=f"statement.{name}_missing", file=src.main_file, symbol=name)
        for name in required
        if name in _HEADING_PATTERNS and name not in satisfied
    ]
