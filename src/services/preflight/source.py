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
    comment). The ``\\begin{...}``/``\\end{...}`` lines of a masked verbatim-like environment are
    copied through unmasked; only the body between them is blanked.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    state = "text"  # text | comment | begin_line | body | end_line
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
                state = "text"
            else:
                out.append(" ")
            i += 1
            continue
        if state == "begin_line":
            out.append(c)
            if c == "\n":
                state = "body"
            i += 1
            continue
        if state == "body":
            if c == "\n":
                out.append(c)
                i += 1
                continue
            match = _END_ENV_RE.match(text, i)
            if match and match.group(1) == env:
                out.append(text[i : match.end()])
                i = match.end()
                state = "end_line"
                continue
            out.append(" ")
            i += 1
            continue
        # state == "end_line"
        out.append(c)
        if c == "\n":
            state = "text"
        i += 1
    return "".join(out)


def _with_tex_extension(target: str) -> str:
    last_segment = target.rsplit("/", 1)[-1]
    if "." in last_segment:
        return target
    return f"{target}.tex"


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
    return PreflightSource(main_file=main_file, files=tuple(resolved), unresolved_includes=tuple(unresolved))
