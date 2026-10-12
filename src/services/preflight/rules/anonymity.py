"""Double-blind anonymity rules for Submission Preflight.

A leaked author identity is the single highest-stakes finding in this whole feature: ICLR 2026
desk-rejects, no discussion, any paper where author identity is revealed anywhere in the main text
or the supplementary material. ``check_anonymity`` reports what it finds; it does not read a
profile and does not decide whether double-blind review applies — the caller runs this module only
when the author has declared ``profile.double_blind``, and the catalogue (not this module) maps
each ``anon.*`` id to a severity. Three ids are ``critical`` (``author_populated``,
``affiliation_populated``, ``email_present``); the rest are ``warning`` or ``info`` — see
``RULE_SEVERITY`` in ``catalogue.py``, never assume from this file alone.

Every check scans ``src.iter_masked()``, never ``text`` — a commented-out ``\\author{Jane Doe}``
is not a leak, but an identity sitting in an ``\\input``-ed appendix IS one, and masking already
treats every file in the include graph alike.

The nine rules, each a short independent scan:

- ``anon.author_populated`` / ``anon.affiliation_populated`` (``critical``): ``\\author``, and
  ``\\institute``/``\\affiliation``/``\\affil``, are allowed to be *present* — every double-blind
  template still puts the command in the source — but their argument must be a recognised
  anonymous placeholder (see ``_ANONYMOUS_PLACEHOLDERS``), not a real name or institution. A
  value that is nothing but LaTeX commands with no visible text (a venue's own anonymising macro,
  e.g. ``\\author{\\anonymousauthors}``) is treated as anonymised rather than as a leak, because a
  false critical here is the worst possible outcome in the whole feature: it would tell an author
  their own venue's official template is unsafe.

- ``anon.email_present`` (``critical``): a plausible email address anywhere in the source,
  including the LaTeX-escaped ``name\\@example.com`` form and ``\\url{mailto:...}``. Deliberately
  narrow — see the comment on ``_EMAIL_RE`` for exactly what is required and why a DOI, a URL, a
  version string, or a ``\\cite{smith@2020}`` key can never match.

- ``anon.orcid_present`` (``warning``): an ORCID iD, either via ``\\orcid{...}`` or the bare
  ``dddd-dddd-dddd-dddX`` form anywhere in prose.

- ``anon.thanks_present`` (``warning``): any ``\\thanks{...}`` footnote. In a double-blind
  submission this command has no innocent use — real papers put the "corresponding author" /
  "equal contribution" / funding-acknowledgement footnote there, and every one of those
  attributes the footnote to a person or a grant.

- ``anon.acknowledgements_present`` (``warning``): an Acknowledgements heading (either English
  spelling) or environment, or the Vietnamese ``Lời cảm ơn`` heading. Unlike the ``statement.*``
  funding rule, this fires on the heading's mere existence — a double-blind draft should not have
  written its acknowledgements yet at all, regardless of what they say.

- ``anon.funding_identifiers`` (``warning``): a grant number in a recognisable shape — a funding
  agency's own prefix (``NSF-1234567``, ``DFG 123456``, ``ERC-2019-ADG``) or an explicit
  grant-number phrase (``Grant No. 12345``, ``grant number 12345``, ``award no. 12345``, ``under
  grant 12345``), including the Vietnamese ``mã số đề tài`` / ``số quyết định`` forms, accented and
  unaccented. A bare four-digit number is a year, not a grant, and must never fire this rule on
  its own — see the comment on ``_AGENCY_PREFIX_RE`` and ``_GRANT_PHRASE_RE``.

- ``anon.self_reference`` (``info``): a temporal back-reference to the authors' own earlier
  publication ("our previous work", "we previously showed"), English and Vietnamese. The signal is
  the back-reference, not first-person writing — a bare "our work" or "we show" is in every paper
  on earth and must stay quiet.

- ``anon.repository_link`` (``info``): a ``github.com/<user>`` or ``gitlab.com/<user>`` URL. A
  bare ``github.com`` with no path never fires (there is no namespace to leak); a link whose
  namespace is a well-known public organisation (``pytorch``, ``huggingface``, ...) is excluded
  too, since citing a tool's public repository reveals nothing about who the authors are — see
  ``_REPO_WELL_KNOWN_NAMESPACES``.

The four aggregate-prone rules — ``email_present``, ``orcid_present``, ``thanks_present``,
``funding_identifiers``, ``acknowledgements_present``, ``self_reference``, and
``repository_link`` — follow the convention this feature settled in ``formatting.py``: one finding
per distinct problem, ``count`` carrying the occurrence total, located at the first occurrence.
``author_populated`` and ``affiliation_populated`` do the same, since a multi-author
``\\author{Jane Doe \\and John Smith}`` is one leak, not two.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from src.services.preflight.catalogue import Finding
from src.services.preflight.source import PreflightSource

# --- shared: balanced-brace argument extraction ------------------------------------------------

# A command name whose match ends exactly on the opening '{' of its mandatory argument — an
# optional star and an optional [..] short-form argument (\author[Running]{Full Name}) may sit
# between the name and that brace.
_AUTHOR_RE = re.compile(r"\\author\*?(?:\s*\[[^\]]*\])?\s*\{")
# \institute / \affiliation / \affil -- listed longest-prefix-first ("affiliation" before
# "affil") purely for readability; Python's alternation backtracks to the right branch regardless
# of order, since the whole pattern (through to the final "{") must match.
_AFFILIATION_RE = re.compile(r"\\(?:affiliation|institute|affil)\*?(?:\s*\[[^\]]*\])?\s*\{")
# \thanks{...} -- the footnote command, star rarely used but accepted for symmetry.
_THANKS_RE = re.compile(r"\\thanks\*?\s*\{")


def _match_braced_arg(text: str, open_brace: int) -> int | None:
    """Index of the ``}`` matching the ``{`` at ``open_brace``, tracking nesting depth so a brace
    inside the argument (``\\thanks{Supported by \\url{https://...}}``) does not end the match
    early. ``None`` if the braces never balance before the text ends."""
    depth = 0
    for i in range(open_brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _iter_brace_commands(masked: str, command_re: re.Pattern[str]) -> Iterator[tuple[re.Match[str], str]]:
    """Yield ``(match, argument_text)`` for every occurrence of ``command_re`` — a pattern whose
    match ends exactly on the opening ``{`` of a mandatory brace argument. The argument is
    extracted with ``_match_braced_arg`` rather than a ``[^}]*`` regex, so nested braces inside it
    (a ``\\thanks`` or ``\\textbf`` wrapping the real content) do not truncate the capture early.
    An argument whose braces never close is skipped rather than guessed at.
    """
    for match in command_re.finditer(masked):
        open_brace = match.end() - 1
        close = _match_braced_arg(masked, open_brace)
        if close is None:
            continue
        yield match, masked[open_brace + 1 : close]


# --- anonymous-placeholder check, shared by author_populated and affiliation_populated --------

# Every LaTeX command token (backslash + letters + optional star), stripped to get the argument's
# *visible* text — a venue's own anonymising macro (\anonymousauthors) is pure markup with nothing
# left over once this is removed, which is exactly the "anonymised" case, not a leak.
_COMMAND_TOKEN_RE = re.compile(r"\\[A-Za-z]+\*?")

# The anonymous-placeholder values a double-blind template actually uses. Compared against the
# argument's visible text, case-insensitively, after stripping markup and collapsing whitespace.
_ANONYMOUS_PLACEHOLDERS = frozenset(
    {
        "",
        "anonymous",
        "anonymous author",
        "anonymous authors",
        "anon.",
    }
)


def _visible_text(raw: str) -> str:
    """``raw`` with every LaTeX command token and brace character removed, whitespace collapsed —
    the plain text a reader would actually see. Command *arguments* are kept (so
    ``\\textbf{Jane Doe}`` still surfaces "Jane Doe"); only the command names and braces go."""
    text = _COMMAND_TOKEN_RE.sub(" ", raw)
    text = text.replace("{", " ").replace("}", " ")
    return " ".join(text.split())


def _is_anonymous_placeholder(raw: str) -> bool:
    return _visible_text(raw).lower() in _ANONYMOUS_PLACEHOLDERS


def _check_author_or_affiliation(src: PreflightSource, command_re: re.Pattern[str], rule: str) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match, raw in _iter_brace_commands(masked, command_re):
            if _is_anonymous_placeholder(raw):
                continue
            count += 1
            if first is None:
                symbol = _visible_text(raw) or raw.strip()
                first = (path, match.start(), symbol)
    if first is None:
        return []
    path, offset, symbol = first
    return [Finding(rule=rule, file=path, line=src.locate(path, offset), symbol=symbol, count=count)]


# --- email -------------------------------------------------------------------------------------

# A plausible email address: a local part, an '@' (or the LaTeX-escaped '\@', typed so LaTeX gets
# normal inter-word spacing after it), a domain of one or more dot-separated labels, and a FINAL
# label that is letters-only and at least two characters — a real TLD. That last requirement is
# what keeps this from matching things that merely look like an address:
#   - a DOI ("10.1145/3292500.3330701") has no '@' anywhere, so it can never start a match.
#   - "\cite{smith@2020}" has an '@' and a local part, but its domain ("2020") is digits with no
#     dot and no letters-only final label, so the domain+TLD tail never matches.
#   - a version string ("v2.1@build.3") fails the same way — no letters-only final label.
# \url{mailto:jane@example.com} needs no special case: the address inside it matches this pattern
# on its own regardless of the \url{mailto:...} wrapper around it.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}\\?@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,}\b"
)


def _check_email_present(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match in _EMAIL_RE.finditer(masked):
            count += 1
            if first is None:
                first = (path, match.start(), match.group(0))
    if first is None:
        return []
    path, offset, symbol = first
    return [Finding(rule="anon.email_present", file=path, line=src.locate(path, offset), symbol=symbol, count=count)]


# --- orcid -------------------------------------------------------------------------------------

# \orcid{<id>} (tried first, so it consumes the id and the command form is never also matched a
# second time by the bare-id branch below) or a bare ORCID iD anywhere in prose
# (dddd-dddd-dddd-dddX, last character a checksum digit or "X").
_ORCID_RE = re.compile(
    r"\\orcid\*?\s*\{\s*(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])\s*\}" r"|\b(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])\b"
)


def _check_orcid_present(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match in _ORCID_RE.finditer(masked):
            orcid_id = match.group(1) or match.group(2) or ""
            count += 1
            if first is None:
                first = (path, match.start(), orcid_id)
    if first is None:
        return []
    path, offset, symbol = first
    return [Finding(rule="anon.orcid_present", file=path, line=src.locate(path, offset), symbol=symbol, count=count)]


# --- thanks ------------------------------------------------------------------------------------


def _check_thanks_present(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match, raw in _iter_brace_commands(masked, _THANKS_RE):
            count += 1
            if first is None:
                excerpt = _visible_text(raw)[:80]
                first = (path, match.start(), excerpt)
    if first is None:
        return []
    path, offset, symbol = first
    return [Finding(rule="anon.thanks_present", file=path, line=src.locate(path, offset), symbol=symbol, count=count)]


# --- acknowledgements ----------------------------------------------------------------------

# "Acknowledgements"/"Acknowledgments" (both spellings, "e" before "ments" optional) as a
# \section/\subsection/\paragraph title, a named \begin{acknowledgements} environment (either
# spelling), or the Vietnamese heading "Lời cảm ơn" / "Loi cam on". Fires on the heading's mere
# presence -- unlike the statement.funding_missing rule, content is irrelevant here: a
# double-blind draft should not have written this section at all yet.
_ACKNOWLEDGEMENTS_TERMS = r"acknowledg(?:e)?ments?" r"|lời\s+cảm\s+ơn" r"|loi\s+cam\s+on"
_ACKNOWLEDGEMENTS_RE = re.compile(
    r"\\(?:(?:sub){0,2}section|paragraph)\*?\s*\{[^}]*(?:" + _ACKNOWLEDGEMENTS_TERMS + r")[^}]*\}"
    r"|\\begin\{\s*acknowledg(?:e)?ments?\s*\}",
    re.IGNORECASE,
)


def _check_acknowledgements_present(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match in _ACKNOWLEDGEMENTS_RE.finditer(masked):
            count += 1
            if first is None:
                first = (path, match.start(), " ".join(match.group(0).split()))
    if first is None:
        return []
    path, offset, symbol = first
    return [
        Finding(
            rule="anon.acknowledgements_present", file=path, line=src.locate(path, offset), symbol=symbol, count=count
        )
    ]


# --- funding identifiers ------------------------------------------------------------------------

# A funding agency's own grant-number shape: the agency's abbreviation, a separator (space or
# hyphen), then a grant code that contains at least one digit somewhere in it (checked in Python,
# not the regex, so "ERC-2019-ADG" — digit first, letters after — is accepted same as
# "NSF-1234567" — digits only). Kept to a fixed, well-known list of funder abbreviations rather
# than "any short uppercase word + digit", specifically so this never fires on an unrelated
# acronym-and-number pairing (a model name like "GPT-4", a standard like "ISO-9001").
_FUNDING_AGENCIES = (
    "NSF",
    "DFG",
    "ERC",
    "NIH",
    "DARPA",
    "ONR",
    "AFOSR",
    "ARO",
    "EPSRC",
    "JSPS",
    "NSFC",
    "ARC",
    "CIHR",
    "SSHRC",
    "NSERC",
    "FWF",
    "ANR",
    "DOE",
    "NASA",
    "NWO",
    "MOST",
    "NRF",
    "NAFOSTED",
)
_AGENCY_PREFIX_RE = re.compile(r"\b(?:" + "|".join(_FUNDING_AGENCIES) + r")[\s-]+([A-Za-z0-9][\w.-]*)\b")

# A bare four-digit number ("2024") must never match this rule on its own — it is a year, not a
# grant — so every alternative below requires either a known agency prefix (above) or an explicit
# grant-number PHRASE, never a number in isolation.
_GRANT_PHRASE_RE = re.compile(
    r"\bgrant\s*(?:no\.?|number)\s*[:#]?\s*\d[\w.-]*"
    r"|\baward\s*no\.?\s*[:#]?\s*\d[\w.-]*"
    r"|\bunder\s+grant\s*[:#]?\s*\d[\w.-]*"
    r"|\bmã\s+số\s+đề\s+tài\b"
    r"|\bma\s+so\s+de\s+tai\b"
    r"|\bsố\s+quyết\s+định\b"
    r"|\bso\s+quyet\s+dinh\b",
    re.IGNORECASE,
)


def _agency_prefix_hits(masked: str) -> Iterator[tuple[int, str]]:
    for match in _AGENCY_PREFIX_RE.finditer(masked):
        if any(ch.isdigit() for ch in match.group(1)):
            yield match.start(), " ".join(match.group(0).split())


def _check_funding_identifiers(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        hits = list(_agency_prefix_hits(masked))
        hits.extend((match.start(), " ".join(match.group(0).split())) for match in _GRANT_PHRASE_RE.finditer(masked))
        for offset, symbol in sorted(hits):
            count += 1
            if first is None:
                first = (path, offset, symbol)
    if first is None:
        return []
    path, offset, symbol = first
    return [
        Finding(rule="anon.funding_identifiers", file=path, line=src.locate(path, offset), symbol=symbol, count=count)
    ]


# --- self reference -------------------------------------------------------------------------

# A TEMPORAL back-reference to the authors' own earlier publication, not merely first-person
# writing: "our previous/prior/earlier work/paper/study/..." or "we previously/earlier
# showed/demonstrated/...". A bare "our work" or "we show" (no temporal qualifier) is in nearly
# every paper on earth and must stay quiet -- the qualifier word is what makes this a disclosure
# that the authors have published on this exact topic before, which is the actual identity signal.
_SELF_REFERENCE_RE = re.compile(
    r"\bour\s+(?:previous|prior|earlier)\s+(?:work|paper|study|research|publication)\b"
    r"|\bin\s+our\s+(?:previous|prior|earlier)\s+(?:work|paper|study)\b"
    r"|\bwe\s+(?:previously|earlier)\s+(?:showed|demonstrated|proposed|introduced|presented|reported)\b"
    r"|\bnghiên\s+cứu\s+trước\s+của\s+chúng\s+tôi\b"
    r"|\bnghien\s+cuu\s+truoc\s+cua\s+chung\s+toi\b"
    r"|\bcông\s+trình\s+trước\s+của\s+chúng\s+tôi\b"
    r"|\bcong\s+trinh\s+truoc\s+cua\s+chung\s+toi\b",
    re.IGNORECASE,
)


def _check_self_reference(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match in _SELF_REFERENCE_RE.finditer(masked):
            count += 1
            if first is None:
                first = (path, match.start(), " ".join(match.group(0).split()))
    if first is None:
        return []
    path, offset, symbol = first
    return [Finding(rule="anon.self_reference", file=path, line=src.locate(path, offset), symbol=symbol, count=count)]


# --- repository link ------------------------------------------------------------------------

# github.com/<namespace>[/<repo>] or gitlab.com/<namespace>[/<repo>]. The namespace segment is
# mandatory (a bare "github.com" with nothing after it can never match -- there is no "/" for the
# namespace group to follow) so a passing mention of the site itself is not a finding.
_REPO_LINK_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?(github|gitlab)\.com/([A-Za-z0-9][\w.-]*)(?:/([A-Za-z0-9][\w.-]*))?",
    re.IGNORECASE,
)

# Well-known public-organisation namespaces: a link to one of these reveals nothing about who the
# AUTHORS are, only which public tool they used (e.g. "built on github.com/pytorch/pytorch"). Not
# exhaustive by design -- it only needs to cover the organisations common enough in ML/CS papers
# that flagging them would otherwise be the single most frequent false "info" in this rule.
_REPO_WELL_KNOWN_NAMESPACES = frozenset(
    {
        "pytorch",
        "tensorflow",
        "huggingface",
        "openai",
        "google",
        "google-research",
        "facebookresearch",
        "microsoft",
        "nvidia",
        "apple",
        "deepmind",
        "allenai",
        "stanfordnlp",
    }
)


def _check_repository_link(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match in _REPO_LINK_RE.finditer(masked):
            if match.group(2).lower() in _REPO_WELL_KNOWN_NAMESPACES:
                continue
            count += 1
            if first is None:
                first = (path, match.start(), match.group(0))
    if first is None:
        return []
    path, offset, symbol = first
    return [Finding(rule="anon.repository_link", file=path, line=src.locate(path, offset), symbol=symbol, count=count)]


def check_anonymity(src: PreflightSource) -> list[Finding]:
    """Run all nine double-blind anonymity checks and concatenate their findings.

    The caller decides whether to call this at all (``profile.double_blind``); this function does
    not read a profile and reports unconditionally once invoked.
    """
    findings: list[Finding] = []
    findings.extend(_check_author_or_affiliation(src, _AUTHOR_RE, "anon.author_populated"))
    findings.extend(_check_author_or_affiliation(src, _AFFILIATION_RE, "anon.affiliation_populated"))
    findings.extend(_check_email_present(src))
    findings.extend(_check_orcid_present(src))
    findings.extend(_check_thanks_present(src))
    findings.extend(_check_acknowledgements_present(src))
    findings.extend(_check_funding_identifiers(src))
    findings.extend(_check_self_reference(src))
    findings.extend(_check_repository_link(src))
    return findings
