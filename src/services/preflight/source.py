from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

# \begin{<env>} opener for the verbatim-like environments whose bodies get masked.
_BEGIN_VERBATIM_RE = re.compile(r"\\begin\{(verbatim|Verbatim|lstlisting|minted|alltt)\}")
# \end{<env>} closer; matched generically, then compared against whichever environment is open.
_END_ENV_RE = re.compile(r"\\end\{([^}]*)\}")
# \input{target} / \include{target} — read off the masked text so commented-out includes are invisible.
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
# Payload entries that hold LaTeX source, i.e. the ones whose labels, citations and bib keys the
# rules are entitled to see. Anything else in a payload (a .bib, a .cls, a .sty) is not source the
# include graph is supposed to reach, so its absence from that graph means nothing.
_TEX_EXTENSIONS = frozenset({".tex", ".latex"})


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str  # original, unmasked
    masked: str  # same length as text; comments and verbatim bodies replaced by spaces


@dataclass(frozen=True)
class PreflightSource:
    main_file: str
    files: tuple[SourceFile, ...]  # in \input-resolution order, main first
    unresolved_includes: tuple[str, ...]  # \input targets absent from the payload, and cycles
    # LaTeX files the payload DID supply that the include graph never reached — see build_source.
    unexamined_files: tuple[str, ...] = ()

    def locate(self, path: str, offset: int) -> int:
        """1-based line of ``offset`` within ``path``'s original text."""
        return self._file(path).text.count("\n", 0, offset) + 1

    def masked_of(self, path: str) -> str:
        return self._file(path).masked

    def iter_masked(self) -> Iterator[tuple[str, str]]:
        for source_file in self.files:
            yield source_file.path, source_file.masked

    def _file(self, path: str) -> SourceFile:
        for source_file in self.files:
            if source_file.path == path:
                return source_file
        raise KeyError(path)


def _mask(text: str) -> str:
    """Blank out comments and verbatim-environment bodies in one left-to-right scan.

    Length and newline positions are preserved: masked characters become a single space, and
    every ``"\\n"`` is copied through unchanged. A ``%`` starts a comment only when preceded by
    an even number of backslashes (``\\%`` is a literal percent, ``\\\\%`` is a line break then a
    comment). The ``\\begin{...}``/``\\end{...}`` tokens of a masked verbatim-like environment are
    copied through unmasked (the float/environment rules depend on seeing them); only the body
    between them is blanked.

    A ``%`` on the same physical line as one of those tokens DOES start a comment, exactly as it
    does in ordinary text -- ``\\begin{lstlisting} % \\linespread{0.5}`` is a comment, not source.
    Copying those two lines through verbatim was this module's one masking hole: nothing was
    looking *for* comments, so every rule that scans the line saw the comment's contents intact
    and ``format.compressed_leading`` / ``crossref.undefined_ref`` fired `critical` on it. The
    comment state therefore carries a resume target (``after_comment``): a comment opened on a
    ``\\begin`` line resumes in the verbatim ``body`` at the newline, one opened on an ``\\end``
    line resumes in ordinary ``text``.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    state = "text"  # text | comment | begin_line | body | end_line
    after_comment = "text"  # state the `comment` state returns to at the end of the line
    env = ""
    backslashes = 0
    while i < n:
        c = text[i]
        if state == "text":
            if c == "\n":
                out.append(c)
                backslashes = 0
                i += 1
                continue
            if c == "%":
                if backslashes % 2 == 0:
                    out.append(" ")
                    after_comment = "text"
                    state = "comment"
                else:
                    out.append(c)
                backslashes = 0
                i += 1
                continue
            if c == "\\":
                match = _BEGIN_VERBATIM_RE.match(text, i)
                if match:
                    env = match.group(1)
                    out.append(text[i : match.end()])
                    i = match.end()
                    state = "begin_line"
                    backslashes = 0
                    continue
                out.append(c)
                backslashes += 1
                i += 1
                continue
            out.append(c)
            backslashes = 0
            i += 1
            continue
        if state == "comment":
            if c == "\n":
                out.append(c)
                state = after_comment
                backslashes = 0
            else:
                out.append(" ")
            i += 1
            continue
        if state in ("begin_line", "end_line"):
            # The remainder of the physical line carrying a \begin{verbatim}/\end{verbatim}
            # token: ordinary LaTeX as far as comments go, so the same even-backslash rule as the
            # `text` state applies. `resume` is where the line ends up -- inside the environment's
            # body after a \begin line, back in ordinary text after an \end line.
            resume = "body" if state == "begin_line" else "text"
            if c == "\n":
                out.append(c)
                state = resume
                backslashes = 0
                i += 1
                continue
            if c == "%":
                if backslashes % 2 == 0:
                    out.append(" ")
                    after_comment = resume
                    state = "comment"
                else:
                    out.append(c)
                backslashes = 0
                i += 1
                continue
            if c == "\\":
                out.append(c)
                backslashes += 1
                i += 1
                continue
            out.append(c)
            backslashes = 0
            i += 1
            continue
        # state == "body" -- every character is blanked until the matching \end{<env>}.
        if c == "\n":
            out.append(c)
            i += 1
            continue
        match = _END_ENV_RE.match(text, i)
        if match and match.group(1) == env:
            out.append(text[i : match.end()])
            i = match.end()
            state = "end_line"
            backslashes = 0
            continue
        out.append(" ")
        i += 1
    return "".join(out)


def _with_tex_extension(target: str) -> str:
    last_segment = target.rsplit("/", 1)[-1]
    if "." in last_segment:
        return target
    return f"{target}.tex"


def _is_tex_path(path: str) -> bool:
    """``True`` for a payload path that holds LaTeX source (see ``_TEX_EXTENSIONS``)."""
    last_segment = path.rsplit("/", 1)[-1]
    dot = last_segment.rfind(".")
    return dot != -1 and last_segment[dot:].lower() in _TEX_EXTENSIONS


def _include_targets(masked: str) -> Iterator[str]:
    for match in _INPUT_RE.finditer(masked):
        yield _with_tex_extension(match.group(1).strip())


def build_source(main_file: str, files: Mapping[str, str]) -> PreflightSource:
    """Resolve ``\\input``/``\\include`` depth-first from ``main_file``, masking each file as it is read.

    ``visited`` makes every file appear at most once in ``files`` (a shared "diamond" include —
    two files both ``\\input``-ing the same third file — is resolved once and silently skipped the
    second time; nothing is missing, so it is not recorded). ``ancestors`` is the current DFS path:
    a target already on it is a true cycle, whose back-edge is recorded in ``unresolved_includes``
    instead of being followed, so a cyclic include graph still returns. A target absent from
    ``files`` altogether is also recorded there.

    ``unexamined_files`` is the mirror image of that, and the reason it exists is the whole point:
    a ``.tex``/``.latex`` file the payload DID supply but the include graph never reached is
    content nobody read. ``_INPUT_RE`` only knows ``\\input`` and ``\\include``, so a project
    wired up with ``\\subfile``, ``\\import``, ``\\subimport``, ``\\InputIfFileExists``,
    ``\\includeonly``, a conditional include or a macro-wrapped one leaves its sections unread —
    and before this field existed every bookkeeping field stayed empty, so the runner happily
    reported ``crossref.undefined_ref`` as `critical` over labels sitting in a file it never
    opened. Recording the paths here instead of growing the command list is deliberate (final
    whole-branch review, ruling 30): the list of commands that can pull in a file is open-ended,
    the set of files nobody read is not. The runner treats a non-empty ``unexamined_files`` exactly
    as it treats a missing ``\\input`` target — suppress the cross-file rules — because spec §4.3's
    policy is "thà im lặng còn hơn bắn critical dựa trên dữ liệu thiếu". It is reported as its own
    field, not folded into ``unresolved_includes``, because the panel must not tell an author a
    file is missing when the file is right there.

    Consequence, accepted: a genuinely unused stray ``.tex`` in the payload also suppresses
    ``crossref.undefined_ref`` and ``bib.uncited_entry``. That is the spec's stated preference —
    silence over a false critical — and the panel names the file, so the author can see exactly
    which one caused it.
    """
    resolved: list[SourceFile] = []
    visited: set[str] = set()
    ancestors: list[str] = []
    unresolved: list[str] = []

    def resolve(path: str) -> None:
        if path in ancestors:
            unresolved.append(path)
            return
        if path in visited:
            return
        visited.add(path)
        text = files.get(path)
        if text is None:
            unresolved.append(path)
            return
        masked = _mask(text)
        resolved.append(SourceFile(path=path, text=text, masked=masked))
        ancestors.append(path)
        for target in _include_targets(masked):
            resolve(target)
        ancestors.pop()

    resolve(main_file)
    read = {source_file.path for source_file in resolved}
    unexamined = tuple(path for path in files if path not in read and _is_tex_path(path))
    return PreflightSource(
        main_file=main_file,
        files=tuple(resolved),
        unresolved_includes=tuple(unresolved),
        unexamined_files=unexamined,
    )
