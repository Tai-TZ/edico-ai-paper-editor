"""Cross-reference rules for Submission Preflight.

Collects every ``\\label`` and every reference command across the whole source (not per file —
a label in an included file satisfies a ``\\ref`` in the main file) and reports four mechanical
faults: a reference with no matching label, a label defined more than once, a float with no
label anywhere inside it, and a label nobody ever references.

Suppression on ``unresolved_includes`` is the runner's job, not this module's: see the design
spec, section 4.3 (``docs/superpowers/specs/2026-10-11-submission-preflight-design.md``). This
rule emits findings unconditionally.
"""

from __future__ import annotations

import re

from src.services.preflight.catalogue import Finding
from src.services.preflight.source import PreflightSource, is_unresolvable_key

# \ref and its cousins: \ref, \eqref, \autoref, \cref, \Cref, \pageref, \vref, each with an
# optional cleveref star. The argument is captured raw because it may hold several comma-separated
# keys (\cref{a,b}).
_REF_RE = re.compile(r"\\(?:eqref|autoref|pageref|cref|Cref|vref|ref)\*?\{([^}]*)\}")
# \label{key} — defines a cross-reference target.
_LABEL_RE = re.compile(r"\\label\{([^}]*)\}")
# Float environments expected to carry a \label somewhere in their body. Starred forms are listed
# before their unstarred prefix so the alternation can't stop one character short.
_FLOAT_RE = re.compile(r"\\begin\{(figure\*|table\*|figure|table|algorithm)\}(.*?)\\end\{\1\}", re.DOTALL)


def check_crossref(src: PreflightSource) -> list[Finding]:
    # (key, file, offset) for every \label and every reference key, in encounter order across
    # src.iter_masked() — \input-resolution order, main file first.
    labels_by_key: dict[str, list[tuple[str, int]]] = {}
    refs: list[tuple[str, str, int]] = []

    for path, masked in src.iter_masked():
        for match in _LABEL_RE.finditer(masked):
            key = match.group(1).strip()
            if not key or is_unresolvable_key(key):
                continue
            labels_by_key.setdefault(key, []).append((path, match.start()))
        for match in _REF_RE.finditer(masked):
            for raw_key in match.group(1).split(","):
                key = raw_key.strip()
                if not key or is_unresolvable_key(key):
                    continue
                refs.append((key, path, match.start()))

    findings: list[Finding] = []

    # crossref.undefined_ref — one finding per unique undefined key (not per occurrence): ten
    # \ref{x} calls to a missing label are one problem (add the label), not ten critical rows.
    # count carries the occurrence total; file/line point at the first occurrence so "go to line"
    # lands somewhere useful.
    undefined_refs: dict[str, tuple[str, int, int]] = {}  # key -> (file, first offset, count)
    for key, path, offset in refs:
        if key in labels_by_key:
            continue
        if key not in undefined_refs:
            undefined_refs[key] = (path, offset, 1)
        else:
            first_path, first_offset, count = undefined_refs[key]
            undefined_refs[key] = (first_path, first_offset, count + 1)
    for key, (path, offset, count) in undefined_refs.items():
        findings.append(
            Finding(
                rule="crossref.undefined_ref",
                file=path,
                line=src.locate(path, offset),
                symbol=key,
                count=count,
            )
        )

    # crossref.float_without_label — a float is clean once any \label appears in its body.
    for path, masked in src.iter_masked():
        for match in _FLOAT_RE.finditer(masked):
            env, body = match.group(1), match.group(2)
            if _LABEL_RE.search(body) is None:
                findings.append(
                    Finding(
                        rule="crossref.float_without_label",
                        file=path,
                        line=src.locate(path, match.start()),
                        symbol=env,
                    )
                )

    # crossref.unused_label — one finding per label key with zero referencing occurrences,
    # reported at the label's first definition.
    referenced_keys = {key for key, _, _ in refs}
    for key, occurrences in labels_by_key.items():
        if key not in referenced_keys:
            path, offset = occurrences[0]
            findings.append(Finding(rule="crossref.unused_label", file=path, line=src.locate(path, offset), symbol=key))

    # crossref.duplicate_label — once per EXTRA definition beyond the first, at the duplicate's line.
    for key, occurrences in labels_by_key.items():
        for path, offset in occurrences[1:]:
            findings.append(
                Finding(rule="crossref.duplicate_label", file=path, line=src.locate(path, offset), symbol=key)
            )

    return findings
