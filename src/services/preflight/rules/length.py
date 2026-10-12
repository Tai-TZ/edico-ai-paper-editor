"""Word-count limit rule for Submission Preflight.

Venues enforce a page or word limit and desk-reject on overrun, but every venue counts
differently: some include captions, some exclude the abstract, some count references, some
measure pages rather than words at all. ``count_body_words`` is therefore an *approximation* of
what a venue will measure, not a reproduction of it — the product surfaces it as an estimate, and
this module's job is to make that estimate defensible and documented, never to pretend it is
exact.

That shapes the one rule governing every ambiguous call below: **when in doubt whether something
counts, count it.** A warning that fires a little early (the estimate came in slightly high) costs
an author a glance; a warning that stays silent because the estimate came in slightly low costs
them a desk rejection after they already submitted. Each ambiguous decision below is called out
with which way it was resolved and why.

What counts, and what does not
-------------------------------
Counted: ordinary body prose, and ``\\caption{...}`` text (most venues count captions toward the
total).

Not counted:

- LaTeX comments — already blanked by ``source.py``'s masking, nothing to do here.
- Everything in the preamble — ``\\documentclass`` through ``\\begin{document}``. The **body** is
  everything between ``\\begin{document}`` and ``\\end{document}``; a file with neither (an
  ``\\input``-ed fragment, which never carries its own document environment) is entirely body.
- Math: inline ``$...$``, display ``$$...$$``, ``\\(...\\)``, ``\\[...\\]``, and the
  ``equation``/``equation*``/``align``/``align*``/``gather``/``multline`` environments. Stripped
  by regex *before* the text ever reaches pylatexenc, because pylatexenc's ``math_mode="text"``
  renders math as readable prose rather than dropping it — exactly the opposite of what this rule
  needs.
- The bibliography tail: ``\\bibliography{...}``, ``\\printbibliography``, or
  ``\\begin{thebibliography}``. The first of these found in a file truncates that file's counted
  body right there — everything from that marker to the end of the body is dropped, not just the
  command itself. This matters for ``\\begin{thebibliography}...\\end{thebibliography}``, whose
  body is real prose-shaped text (hand-typed reference entries) that pylatexenc would otherwise
  convert to real, counted words.

Conversion and counting
------------------------
``LatexNodes2Text`` (pylatexenc, already a dependency — see
``src/services/citations/title_match.py``) turns the surviving, math-stripped LaTeX into plain
text; a "word" is then whatever ``str.split()`` finds between runs of whitespace. This is net-new
in the repo — there is no existing word counter to reuse — so no hand-rolled macro-stripping
regex chain is attempted beyond the math/bibliography carve-outs above: pylatexenc already knows
how to turn ``\\section{Intro}``, ``\\textbf{bold}``, ``\\cite{foo}``, and an unknown macro into
something word-count-shaped, and re-deriving that by hand would just reinvent it worse.

A conversion failure (malformed input pylatexenc cannot parse) falls back to counting the raw,
still-LaTeX-flavoured text rather than raising — a degraded count that still leans high, never a
crashed preflight run.
"""

from __future__ import annotations

import re

from pylatexenc.latex2text import LatexNodes2Text

from src.services.preflight.catalogue import Finding
from src.services.preflight.source import PreflightSource

# \begin{document} / \end{document} -- the preamble/body boundary. A file with neither (an
# \input-ed fragment) is entirely body: see module docstring.
_BEGIN_DOCUMENT_RE = re.compile(r"\\begin\{document\}")
_END_DOCUMENT_RE = re.compile(r"\\end\{document\}")

# The earliest of these three starts the bibliography tail that gets dropped: \bibliography{...}
# and \printbibliography are the biblatex/BibTeX commands that pull in the rendered reference
# list at compile time (no body of their own to strip); \begin{thebibliography} opens a manually
# typed reference list whose body IS real text, so everything from its opener onward is dropped
# too, not just the command.
_BIBLIOGRAPHY_TAIL_RE = re.compile(r"\\bibliography\{[^}]*\}" r"|\\printbibliography\b" r"|\\begin\{thebibliography\}")

# \begin{equation|equation*|align|align*|gather|multline}...\end{<same name>} -- the \1
# backreference requires the closing environment name to match the opener exactly (including the
# star), so a malformed/mismatched pair is simply left unmatched rather than guessed at.
_MATH_ENV_RE = re.compile(r"\\begin\{(equation\*?|align\*?|gather|multline)\}.*?\\end\{\1\}", re.DOTALL)
# Display math $$...$$ -- matched, and stripped, before the single-dollar pattern below so a
# "$$...$$" pair is consumed as one span instead of being misread as two empty "$...$" runs.
_DISPLAY_DOLLAR_MATH_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
# Inline math $...$. The dollar on either side must not itself be escaped (\$ is a literal dollar
# sign, not a delimiter); inside the span, an escaped character (\$, \%, ...) is skipped as a unit
# so it can never be misread as the closing delimiter.
_INLINE_DOLLAR_MATH_RE = re.compile(r"(?<!\\)\$(?:[^$\\]|\\.)*?(?<!\\)\$")
# \(...\) and \[...\] -- LaTeX's other two math delimiter pairs.
_PAREN_MATH_RE = re.compile(r"\\\(.*?\\\)", re.DOTALL)
_BRACKET_MATH_RE = re.compile(r"\\\[.*?\\\]", re.DOTALL)

# math_mode="text" matches the convention in citations/title_match.py: by the time this instance
# ever sees a "$", the regexes above have already failed to strip it (malformed input), so
# rendering it as readable text rather than raising is the same "lean high" fallback as the rest
# of this module, not a contradiction of the "strip math first" rule above.
_LATEX_TO_TEXT = LatexNodes2Text(math_mode="text")


def _extract_body(masked: str) -> str:
    """Everything between ``\\begin{document}`` and ``\\end{document}``, or the whole file when
    either is absent (an ``\\input``-ed fragment has no document environment at all)."""
    begin = _BEGIN_DOCUMENT_RE.search(masked)
    end = _END_DOCUMENT_RE.search(masked)
    start = begin.end() if begin is not None else 0
    stop = end.start() if end is not None else len(masked)
    if stop < start:
        stop = len(masked)
    return masked[start:stop]


def _drop_bibliography_tail(body: str) -> str:
    match = _BIBLIOGRAPHY_TAIL_RE.search(body)
    if match is None:
        return body
    return body[: match.start()]


def _strip_math(text: str) -> str:
    """Blank every math span to a single space (not an empty string) so two words that sat on
    either side of it, e.g. ``"holds.$x$next"``, never fuse into one token."""
    text = _MATH_ENV_RE.sub(" ", text)
    text = _DISPLAY_DOLLAR_MATH_RE.sub(" ", text)
    text = _INLINE_DOLLAR_MATH_RE.sub(" ", text)
    text = _PAREN_MATH_RE.sub(" ", text)
    text = _BRACKET_MATH_RE.sub(" ", text)
    return text


def _to_plain_text(text: str) -> str:
    try:
        return _LATEX_TO_TEXT.latex_to_text(text)
    except Exception:
        # Malformed input pylatexenc cannot parse: fall back to the raw, still-LaTeX-flavoured
        # text rather than crashing the preflight run. Counting markup tokens as words leans the
        # estimate high, which is the direction this rule is supposed to err in anyway.
        return text


def _count_file_words(masked: str) -> int:
    body = _extract_body(masked)
    body = _drop_bibliography_tail(body)
    body = _strip_math(body)
    return len(_to_plain_text(body).split())


def count_body_words(src: PreflightSource) -> int:
    """Approximate word count of ``src``'s body prose and captions, summed across every file.

    Each file is reduced independently (its own body slice, its own bibliography-tail cut, its
    own math strip) and the per-file counts are summed — an ``\\input``-ed file contributes its
    own word count on top of whatever literal text surrounds the ``\\input{...}`` call in the
    file that included it (which pylatexenc renders as nothing, so there is no double count)."""
    return sum(_count_file_words(masked) for _path, masked in src.iter_masked())


def check_length(src: PreflightSource, word_limit: int) -> list[Finding]:
    """``length.over_limit`` strictly above ``word_limit``; ``length.near_limit`` from 95% of it
    up to and including it; silent below that. Mutually exclusive by construction (the ``elif``
    below never lets both branches fire), and the only caller contract is that ``check_length`` is
    invoked at all only when the author declared a word limit, so ``word_limit`` is assumed to
    already be a positive int — this function does not read a profile to decide that.

    The finding has no single meaningful location (the overrun is a property of the whole
    document, not one line of it), so ``file`` is the main file and ``line`` stays ``None`` — the
    same convention ``check_statements`` uses for a missing statement. ``word_limit`` goes in
    ``symbol`` so the panel can render "1,240 words against a 1,000-word limit" without a second
    lookup; the measured count is ``count`` on every finding this emits.
    """
    count = count_body_words(src)
    if count > word_limit:
        rule = "length.over_limit"
    elif count * 20 >= word_limit * 19:  # count >= 0.95 * word_limit, via integer cross-multiplication
        rule = "length.near_limit"
    else:
        return []
    return [Finding(rule=rule, file=src.main_file, symbol=str(word_limit), count=count)]
