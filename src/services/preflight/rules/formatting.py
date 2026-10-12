"""Formatting-manipulation rules for Submission Preflight.

Venues desk-reject papers for squeezing content past a page limit by compressing line spacing,
shrinking margins, or nipping vertical space out of the layout. Four independent checks, scanned
across ``src.iter_masked()`` so a trick hidden in an ``\\input``-ed file is caught the same as one
in the main file, and never scanned from inside a ``verbatim``/``lstlisting`` block, because the
masking already blanked those bodies — a listing showing ``\\linespread{0.9}`` as example code is
not a formatting change.

- ``format.compressed_leading`` (``critical``): a leading (line-spacing) factor strictly below
  ``1.0``, set via ``\\linespread``, ``\\setstretch``, or ``\\renewcommand{\\baselinestretch}``.
  ``\\linespread{1.5}`` (double-spacing, e.g. for a thesis) is left alone — only a factor that
  *shrinks* leading below its natural value is the page-squeezing move. Critical severity means
  this has to be right: a non-numeric or comma-decimal argument is rejected rather than guessed
  at, so a malformed document never produces a wrong critical finding.

- ``format.margin_override`` (``warning``): a margin-changing construct (the ``geometry``,
  ``fullpage``, or ``vmargin`` package, the ``geometry`` package's own ``\\geometry{...}``
  command, or an explicit ``\\setlength``/``\\addtolength`` on a margin-related length register),
  gated on the document class declared by ``\\documentclass[...]{name}``. With a plain class
  (``article``, ``report``, ``book``, ``memoir``, ``scrartcl``) changing margins is completely
  ordinary — a short paper padding itself out, a thesis matching a university template — and
  flagging it would be the single most likely false positive in this module. With any other class
  the venue has already dictated the margins via its own class file, so an override is a real
  signal. No ``\\documentclass`` anywhere (an ``\\input``-ed fragment has none) is treated as
  plain, same as an explicit plain class: there is nothing to override instructions for.

- ``format.large_negative_vspace`` (``warning``): a ``\\vspace{-...}``/``\\vspace*{-...}`` whose
  magnitude is at least ~1em in every unit a real paper uses. One finding aggregates every
  offending occurrence, carrying the total in ``count`` and pointing at the first one — matching
  how ``crossref.undefined_ref`` was settled: one finding per problem, not one row per command.
  The per-unit thresholds (see ``_VSPACE_THRESHOLD``) all sit at the same "about 1em" magnitude,
  using the approximate equivalence 1em ~ 12pt ~ 4.2mm ~ 0.42cm ~ 0.17in ~ 1 baselineskip; a small
  negative nudge (``-2pt``, tightening a figure caption) stays quiet.

- ``format.font_size_override`` (``warning``): a bare ``\\fontsize{size}{skip}`` in the body
  (after ``\\begin{document}``; the whole file counts as body when there is no
  ``\\begin{document}``, i.e. an ``\\input``-ed fragment). A class or package setting up its size
  commands in the preamble is normal and is not scanned.
"""

from __future__ import annotations

import re

from src.services.preflight.catalogue import Finding
from src.services.preflight.source import PreflightSource

# --- compressed leading ----------------------------------------------------------------------

# \linespread{x} | \setstretch{x} | \renewcommand{\baselinestretch}{x} -- the three ways a
# document scales its line spacing. Exactly one of the three capture groups is non-None per match.
_LEADING_RE = re.compile(
    r"\\linespread\{([^}]*)\}" r"|\\setstretch\{([^}]*)\}" r"|\\renewcommand\{\\baselinestretch\}\{([^}]*)\}"
)


def _parse_leading_value(raw: str) -> float | None:
    """A plain decimal factor such as ``0.92`` or ``.92``. ``0,92`` uses a comma decimal
    separator, which is not valid LaTeX, and a non-numeric argument (a macro, an empty brace) is
    equally rejected -- both return ``None`` rather than raising, so a malformed document never
    crashes the rule."""
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _check_compressed_leading(src: PreflightSource) -> list[Finding]:
    findings: list[Finding] = []
    for path, masked in src.iter_masked():
        for match in _LEADING_RE.finditer(masked):
            raw = next(group for group in match.groups() if group is not None)
            value = _parse_leading_value(raw)
            if value is None or value >= 1.0:
                continue
            findings.append(
                Finding(
                    rule="format.compressed_leading",
                    file=path,
                    line=src.locate(path, match.start()),
                    symbol=raw.strip(),
                )
            )
    return findings


# --- margin override --------------------------------------------------------------------------

# \documentclass[options]{name} -- the optional argument comes first and may itself contain
# commas and spaces (e.g. [11pt,twocolumn]), so it is skipped over rather than parsed.
_DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]*)\}")
# Classes where the venue has not already dictated margins -- changing them here is ordinary.
_PLAIN_DOCUMENT_CLASSES = frozenset({"article", "report", "book", "memoir", "scrartcl"})

# \usepackage[options]{name1,name2,...} -- \usepackage can load several packages in one call, so
# the brace content is split on commas in Python rather than matched package-by-package.
_USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}")
# Packages whose entire purpose is changing the page's margins/geometry.
_MARGIN_PACKAGES = frozenset({"geometry", "fullpage", "vmargin"})
# \geometry{...} -- the geometry package's own command for re-setting margins mid-preamble.
_GEOMETRY_COMMAND_RE = re.compile(r"\\geometry\{[^}]*\}")
# Length registers that directly control the page's margins/typeblock.
_MARGIN_LENGTH_REGISTERS = frozenset(
    {
        "textwidth",
        "textheight",
        "oddsidemargin",
        "evensidemargin",
        "topmargin",
        "marginparwidth",
        "marginparsep",
        "hoffset",
        "voffset",
        "headheight",
        "headsep",
        "footskip",
        "columnsep",
    }
)
_MARGIN_LENGTH_RE = re.compile(
    r"\\(?:setlength|addtolength)\{\\(" + "|".join(sorted(_MARGIN_LENGTH_REGISTERS)) + r")\}\{[^}]*\}"
)


def _is_plain_document_class(src: PreflightSource) -> bool:
    """The first ``\\documentclass`` found anywhere is plain, or there is none at all."""
    for _path, masked in src.iter_masked():
        match = _DOCUMENTCLASS_RE.search(masked)
        if match is not None:
            return match.group(1).strip() in _PLAIN_DOCUMENT_CLASSES
    return True


def _margin_override_hits(masked: str) -> list[tuple[int, str]]:
    """Every margin-affecting construct in ``masked``, as ``(offset, label)`` pairs sorted by
    offset -- the three source regexes are matched independently, so the results need re-sorting
    to recover the order the constructs actually appear in the file."""
    hits: list[tuple[int, str]] = []
    for match in _USEPACKAGE_RE.finditer(masked):
        names = {name.strip() for name in match.group(1).split(",")}
        used = names & _MARGIN_PACKAGES
        if used:
            hits.append((match.start(), sorted(used)[0]))
    for match in _GEOMETRY_COMMAND_RE.finditer(masked):
        hits.append((match.start(), "geometry"))
    for match in _MARGIN_LENGTH_RE.finditer(masked):
        hits.append((match.start(), match.group(1)))
    hits.sort(key=lambda hit: hit[0])
    return hits


def _check_margin_override(src: PreflightSource) -> list[Finding]:
    if _is_plain_document_class(src):
        return []
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for offset, label in _margin_override_hits(masked):
            count += 1
            if first is None:
                first = (path, offset, label)
    if first is None:
        return []
    path, offset, symbol = first
    return [
        Finding(
            rule="format.margin_override",
            file=path,
            line=src.locate(path, offset),
            symbol=symbol,
            count=count,
        )
    ]


# --- large negative vspace --------------------------------------------------------------------

# \vspace{...} / \vspace*{...} -- the starred form survives a page break, which is the form that
# actually matters for squeezing a page limit, so both are scanned alike.
_VSPACE_RE = re.compile(r"\\vspace\*?\{([^}]*)\}")
# A dimension's magnitude and unit, once the leading "-" has been stripped: an optional decimal
# number (absent only for the \baselineskip form, where it defaults to 1) followed by one of the
# units a real paper uses -- a plain unit keyword (em/ex/pt/mm/cm/in) or the \baselineskip skip
# register, which TeX accepts as a value on its own.
_VSPACE_AMOUNT_RE = re.compile(r"^([0-9]*\.?[0-9]*)\s*\\?(em|ex|pt|mm|cm|in|baselineskip)\b")

# Per-unit threshold for "large", all pinned to the same ~1em magnitude via the approximate
# equivalence 1em ~ 12pt ~ 4.2mm ~ 0.42cm ~ 0.17in ~ 1 baselineskip. ex has no standard conversion
# given in the brief; 1ex is conventionally about 0.43em (an x-height, not a font size), so
# roughly 2.3 of them make up one em -- used here as 2.3ex, erring slightly toward catching more
# rather than fewer borderline cases, since this rule is a warning, not a critical.
_VSPACE_THRESHOLD: dict[str, float] = {
    "pt": 12.0,
    "em": 1.0,
    "ex": 2.3,
    "mm": 4.2,
    "cm": 0.42,
    "in": 0.17,
    "baselineskip": 1.0,
}


def _parse_negative_vspace(raw: str) -> tuple[str, float] | None:
    """``(unit, magnitude)`` if ``raw`` is a negative dimension in a recognised unit, else
    ``None``. A positive or zero amount, or one this cannot parse (an unrecognised unit, a bare
    macro), returns ``None`` rather than raising."""
    text = raw.strip()
    if not text.startswith("-"):
        return None
    text = text[1:].strip()
    match = _VSPACE_AMOUNT_RE.match(text)
    if match is None:
        return None
    number, unit = match.group(1), match.group(2).lower()
    if not number:
        if unit != "baselineskip":
            return None  # "em"/"pt"/... require an explicit coefficient; \baselineskip alone means 1
        return unit, 1.0
    return unit, float(number)


def _check_large_negative_vspace(src: PreflightSource) -> list[Finding]:
    count = 0
    first: tuple[str, int, str] | None = None
    for path, masked in src.iter_masked():
        for match in _VSPACE_RE.finditer(masked):
            parsed = _parse_negative_vspace(match.group(1))
            if parsed is None:
                continue
            unit, magnitude = parsed
            if magnitude < _VSPACE_THRESHOLD[unit]:
                continue
            count += 1
            if first is None:
                first = (path, match.start(), match.group(1).strip())
    if first is None:
        return []
    path, offset, symbol = first
    return [
        Finding(
            rule="format.large_negative_vspace",
            file=path,
            line=src.locate(path, offset),
            symbol=symbol,
            count=count,
        )
    ]


# --- font size override -----------------------------------------------------------------------

# \begin{document} -- the preamble/body boundary; \fontsize before it is routine class/package
# setup, after it is a manual override of a specific piece of body text.
_BEGIN_DOCUMENT_RE = re.compile(r"\\begin\{document\}")
# \fontsize{size}{baselineskip} -- both arguments are mandatory.
_FONTSIZE_RE = re.compile(r"\\fontsize\{([^}]*)\}\{[^}]*\}")


def _check_font_size_override(src: PreflightSource) -> list[Finding]:
    findings: list[Finding] = []
    for path, masked in src.iter_masked():
        begin_match = _BEGIN_DOCUMENT_RE.search(masked)
        body_start = begin_match.end() if begin_match is not None else 0
        for match in _FONTSIZE_RE.finditer(masked, body_start):
            findings.append(
                Finding(
                    rule="format.font_size_override",
                    file=path,
                    line=src.locate(path, match.start()),
                    symbol=match.group(1).strip(),
                )
            )
    return findings


def check_formatting(src: PreflightSource) -> list[Finding]:
    """Run all four formatting-manipulation checks and concatenate their findings."""
    findings: list[Finding] = []
    findings.extend(_check_compressed_leading(src))
    findings.extend(_check_margin_override(src))
    findings.extend(_check_large_negative_vspace(src))
    findings.extend(_check_font_size_override(src))
    return findings
