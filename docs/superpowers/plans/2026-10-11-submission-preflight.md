# Submission Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Tools-panel tab that lists the mechanical, deterministic faults behind most desk rejections — undefined `\ref`, BibTeX hygiene, missing data-availability/ethics/COI statements, compressed leading, double-blind identity leaks, word-count overruns — each clickable to the exact file and line.

**Architecture:** A pure Python rule engine (`src/services/preflight/`) over a normalized source model that masks comments and verbatim blocks and resolves `\input`/`\include` across the project's files. One stateless authenticated endpoint `POST /api/v1/preflight/run` receives the file set in the request body and returns structured findings — rule ids and offending symbols, never prose. The React panel renders EN/VI copy keyed by rule id, so the backend stays free of UI text.

**Tech Stack:** Python 3.11+ / FastAPI / Pydantic v2 / pytest (+pytest-asyncio, STRICT) · React 19 / TypeScript / vitest (`environment: "node"`)

**Spec:** [docs/superpowers/specs/2026-10-11-submission-preflight-design.md](../specs/2026-10-11-submission-preflight-design.md)

## Global Constraints

- **Advisory only.** `integrity_mode: "comment_only"`. Nothing in this feature writes to a document, blocks an export, or applies an edit. Invariant #1 Human Supremacy.
- **No network, no LLM.** "Missing DOI" means *the entry has no `doi` field*, never *the DOI does not resolve*. Never call `enforce_llm_quota_for_paper` — it consumes the per-minute rate-limit budget (`quota_policy.py:119`), so a free static check would burn the user's LLM quota.
- **Never modify existing behaviour.** Do not edit `src/services/parser/latex.py` (including `CITE_RE`), the two tab-hijacking effects at `ToolsPanel.tsx:99-109`, or any existing i18n value. Call existing helpers; do not change them.
- **Lines are 1-based** and computed against a `\r?\n` split, matching `latex-outline.ts:8` (`lineAtOffset` never returns 0). Any other convention puts every jump off by one.
- **Python style** (from `src/services/parser/latex.py` and `ruff.toml`): `from __future__ import annotations` first; regexes compiled at module level with a `#` comment above each non-obvious one; `UPPER_CASE` for exported regexes, `_LEADING_UNDERSCORE` for internal; builtin generics (`list[dict]`, `int | None`) — ruff `UP` forbids `Optional[...]`; `frozenset({...})` for command sets; line-length 120 with E501 ignored.
- **`src/services/preflight/rules/*` return plain frozen dataclasses, never Pydantic.** Pydantic lives only in `src/models/preflight_schemas.py` — every existing `response_model` in the repo is under `src/models/`.
- **Bilingual UI copy is mandatory** (CLAUDE.md). `.tsx` files export only components; hooks, i18n and API clients must be `.ts`.
- **vitest only collects `src/**/*.test.ts`** — a `.test.tsx` file silently never runs. `environment: "node"`: no `window`, `document`, or `localStorage` in tests.
- **pytest-asyncio is STRICT with no config file in the repo** — every async test needs an explicit `@pytest.mark.asyncio` or it is silently skipped. Pure rule tests are plain `def`.

## Review Focus

Five inputs the spec implies but whose tests would otherwise be missing. Each line's test is assigned to the task that owns the code.

1. **Escaped percent `\%`** — in any paper writing "95\% accuracy", a naive comment stripper truncates the line and corrupts every line number after it. `\%` is not a comment. (Task 1)
2. **`\input` cycle** — `a.tex` inputs `b.tex` inputs `a.tex` must terminate with the cycle recorded, not hang the request. (Task 1)
3. **`\newcommand{\myref}[1]{\ref{#1}}`** — a macro definition wrapping `\ref` must not report `#1` as an undefined label; papers that define reference macros would otherwise see a critical finding per macro. (Task 3)
4. **Violations inside `verbatim`/`lstlisting`** — a methods paper showing `\linespread{0.9}` in a code listing must produce no finding; the sample is content, not formatting. (Task 1 masks it; Task 6 asserts it)
5. **CRLF line endings** — documents from Windows editors and Overleaf ZIP imports must report the same line numbers as the frontend's `\r?\n` split. (Task 1)

---

### Task 1: Normalized source model

Everything else reads this. It is the only module that knows how to strip comments, mask verbatim blocks, and stitch `\input`ed files together, so no rule re-invents those and no rule grows its own false positives.

**Files:**
- Create: `src/services/preflight/__init__.py` (empty)
- Create: `src/services/preflight/source.py`
- Create: `tests/test_preflight/__init__.py` (empty)
- Create: `tests/test_preflight/test_source.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```python
  @dataclass(frozen=True)
  class SourceFile:
      path: str
      text: str          # original, unmasked
      masked: str        # same length as text; comments and verbatim bodies replaced by spaces

  @dataclass(frozen=True)
  class PreflightSource:
      main_file: str
      files: tuple[SourceFile, ...]           # in \input-resolution order, main first
      unresolved_includes: tuple[str, ...]    # \input targets absent from the payload, and cycles

      def locate(self, path: str, offset: int) -> int    # 1-based line of offset within that file
      def masked_of(self, path: str) -> str
      def iter_masked(self) -> Iterator[tuple[str, str]]  # (path, masked) over every file

  def build_source(main_file: str, files: Mapping[str, str]) -> PreflightSource
  ```
  `masked` preserves length and newline positions so an offset in `masked` is the same offset in `text` — that is what keeps `locate` honest.

- [ ] **Step 1: Write the failing tests**

```python
_PAPER = "Accuracy was 95\\% on test.\n% a real comment with \\label{ghost}\nText.\n"

def test_escaped_percent_is_not_a_comment():
    src = build_source("main.tex", {"main.tex": _PAPER})
    masked = src.masked_of("main.tex")
    assert "95\\% on test." in masked          # survives
    assert "ghost" not in masked                # the real comment is gone

def test_mask_preserves_offsets_and_line_count():
    src = build_source("main.tex", {"main.tex": _PAPER})
    masked = src.masked_of("main.tex")
    assert len(masked) == len(_PAPER)
    assert masked.count("\n") == _PAPER.count("\n")

def test_verbatim_body_is_masked():
    doc = "a\n\\begin{lstlisting}\n\\linespread{0.9}\n\\end{lstlisting}\nb\n"
    masked = build_source("main.tex", {"main.tex": doc}).masked_of("main.tex")
    assert "linespread" not in masked

def test_crlf_lines_match_the_frontend_split():
    doc = "one\r\ntwo\r\n\\label{x}\r\n"
    src = build_source("main.tex", {"main.tex": doc})
    assert src.locate("main.tex", doc.index("\\label")) == 3

def test_input_is_resolved_in_order():
    files = {"main.tex": "A\n\\input{sec/one}\n", "sec/one.tex": "\\label{deep}\n"}
    src = build_source("main.tex", files)
    assert [f.path for f in src.files] == ["main.tex", "sec/one.tex"]

def test_missing_input_is_recorded_not_raised():
    src = build_source("main.tex", {"main.tex": "\\input{nope}\n"})
    assert "nope.tex" in src.unresolved_includes

def test_input_cycle_terminates():
    files = {"a.tex": "\\input{b}\n", "b.tex": "\\input{a}\n"}
    src = build_source("a.tex", files)             # must return, not hang
    assert [f.path for f in src.files] == ["a.tex", "b.tex"]
    assert "a.tex" in src.unresolved_includes      # the back-edge is reported, not followed

def test_commented_out_input_is_not_followed():
    src = build_source("main.tex", {"main.tex": "% \\input{sec/one}\n"})
    assert src.unresolved_includes == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.preflight'`

- [ ] **Step 3: Implement `source.py`**

Masking is a single left-to-right scan, not a chain of regex substitutions — a regex pass cannot know whether a `%` sits inside an already-masked verbatim body. Walk the text once, tracking whether the cursor is in a comment, in a verbatim environment, or in ordinary text; replace masked characters with `" "` and copy `"\n"` through unchanged. A `%` is a comment start only when the preceding backslash count is even. Resolve `\input`/`\include` depth-first over the **masked** text (so commented-out includes are invisible), appending `.tex` when the target has no extension, keeping a `visited: set[str]` so a cycle records the back-edge in `unresolved_includes` instead of recursing. `locate` counts `"\n"` in `text[:offset]` and adds 1.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_source.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check src/services/preflight tests/test_preflight && .venv/bin/python -m ruff format src/services/preflight tests/test_preflight
git add src/services/preflight tests/test_preflight
git commit -m "feat(preflight): normalized LaTeX source with comment masking and include resolution"
```

---

### Task 2: Rule catalogue and schemas

**Files:**
- Create: `src/services/preflight/catalogue.py`
- Create: `src/models/preflight_schemas.py`
- Create: `tests/test_preflight/test_catalogue.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```python
  # catalogue.py
  PREFLIGHT_RULE_IDS: tuple[str, ...]   # all 29 ids from spec §3, in group order
                                        # 4 crossref + 5 bib + 5 statement + 4 format + 9 anon + 2 length
  PREFLIGHT_GROUPS: tuple[str, ...] = ("crossref", "bib", "statement", "format", "anon", "length")

  @dataclass(frozen=True)
  class Finding:                        # what every rule returns; runner converts to Pydantic
      rule: str
      file: str = ""
      line: int | None = None
      symbol: str = ""
      count: int = 1
      excerpt: str = ""

  RULE_SEVERITY: Mapping[str, str]      # rule id → "critical" | "warning" | "info"
  ```
  ```python
  # src/models/preflight_schemas.py — exactly the models in spec §4.2 and §4.3:
  # PreflightSeverity, PreflightGroup, RequiredStatement, PreflightProfile,
  # PreflightFinding, PreflightReport, PreflightFile, PreflightRequest
  ```
  `main_file` on `PreflightRequest` reuses the existing validator: `@field_validator("main_file", mode="before")` calling `validate_main_file_path` (the same helper `CompileRequest` uses, `src/models/schemas.py:296-300`).

- [ ] **Step 1: Write the failing test**

```python
def test_every_rule_id_is_group_qualified_and_unique():
    assert len(set(PREFLIGHT_RULE_IDS)) == len(PREFLIGHT_RULE_IDS)
    for rule in PREFLIGHT_RULE_IDS:
        group, _, name = rule.partition(".")
        assert group in PREFLIGHT_GROUPS, rule
        assert name, rule

def test_every_rule_has_a_severity():
    assert set(RULE_SEVERITY) == set(PREFLIGHT_RULE_IDS)
    assert set(RULE_SEVERITY.values()) <= {"critical", "warning", "info"}

def test_only_the_spec_s_rules_are_critical():
    critical = {r for r, s in RULE_SEVERITY.items() if s == "critical"}
    assert critical == {
        "crossref.undefined_ref",
        "crossref.duplicate_label",
        "bib.cite_key_missing",
        "format.compressed_leading",
        "anon.author_populated",
        "anon.affiliation_populated",
        "anon.email_present",
        "length.over_limit",
    }

def test_profile_defaults_match_the_spec():
    p = PreflightProfile()
    assert p.double_blind is False and p.word_limit is None
    assert p.required_statements == ["data_availability", "ethics", "coi", "funding"]

def test_request_rejects_an_unsafe_main_file():
    with pytest.raises(ValidationError):
        PreflightRequest(main_file="../etc/passwd")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_catalogue.py -v`
Expected: FAIL — cannot import `PREFLIGHT_RULE_IDS`

- [ ] **Step 3: Implement `catalogue.py` and `src/models/preflight_schemas.py`**

Take the 29 rule ids and their severities verbatim from spec §3; the `critical` set is pinned by the test above. Models are copied from spec §4.2/§4.3 as written.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_catalogue.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/catalogue.py src/models/preflight_schemas.py tests/test_preflight/test_catalogue.py
git commit -m "feat(preflight): rule catalogue and request/report schemas"
```

---

### Task 3: Cross-reference rules

**Files:**
- Create: `src/services/preflight/rules/__init__.py` (empty)
- Create: `src/services/preflight/rules/crossref.py`
- Create: `tests/test_preflight/test_crossref.py`

**Interfaces:**
- Consumes: `PreflightSource` (Task 1), `Finding` (Task 2).
- Produces: `def check_crossref(src: PreflightSource) -> list[Finding]` — emits `crossref.undefined_ref`, `crossref.duplicate_label`, `crossref.float_without_label`, `crossref.unused_label`.

- [ ] **Step 1: Write the failing tests**

```python
def _rules(doc, **extra):
    files = {"main.tex": doc, **extra}
    return [f.rule for f in check_crossref(build_source("main.tex", files))]

def test_ref_without_label_is_reported():
    out = check_crossref(build_source("main.tex", {"main.tex": "See \\ref{fig:a}.\n"}))
    assert [(f.rule, f.symbol, f.line) for f in out] == [("crossref.undefined_ref", "fig:a", 1)]

def test_label_in_an_included_file_satisfies_the_ref():
    assert "crossref.undefined_ref" not in _rules(
        "\\input{sec/one}\nSee \\ref{fig:a}.\n", **{"sec/one.tex": "\\label{fig:a}\n"}
    )

def test_newcommand_wrapping_ref_does_not_report_the_parameter():
    assert _rules("\\newcommand{\\myref}[1]{\\ref{#1}}\n") == []

def test_cref_and_eqref_are_covered():
    assert _rules("\\eqref{eq:1} \\cref{sec:2}\n").count("crossref.undefined_ref") == 2

def test_duplicate_label_is_reported_once_per_extra_definition():
    assert _rules("\\label{x}\n\\label{x}\n").count("crossref.duplicate_label") == 1

def test_float_without_label_is_reported():
    assert "crossref.float_without_label" in _rules(
        "\\begin{figure}\\includegraphics{a}\\end{figure}\n"
    )

def test_unused_label_is_info_not_silence():
    assert "crossref.unused_label" in _rules("\\label{unused}\n")

def test_commented_ref_is_ignored():
    assert _rules("% \\ref{ghost}\n") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_crossref.py -v`
Expected: FAIL — `check_crossref` undefined

- [ ] **Step 3: Implement `check_crossref`**

Collect labels and references over `src.iter_masked()`. Reference commands to match: `\ref`, `\eqref`, `\autoref`, `\cref`, `\Cref`, `\pageref`, `\vref` — a comma-separated argument may hold several keys (`\cref{a,b}`). A reference whose key contains `#` is a macro parameter, not a label: skip it. Suppress `crossref.undefined_ref` entirely when `src.unresolved_includes` is non-empty — a missing file makes every label look undefined, and a wall of false criticals is worse than silence.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_crossref.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/rules tests/test_preflight/test_crossref.py
git commit -m "feat(preflight): cross-reference rules"
```

---

### Task 4: Bibliography rules

**Files:**
- Create: `src/services/preflight/rules/bibliography.py`
- Create: `tests/test_preflight/test_bibliography.py`

**Interfaces:**
- Consumes: `PreflightSource` (Task 1), `Finding` (Task 2).
- Produces:
  ```python
  def collect_cite_keys(src: PreflightSource) -> dict[str, tuple[str, int]]   # key → (file, line)
  def check_bibliography(src: PreflightSource, bib_content: str) -> list[Finding]
  ```
  Emits `bib.cite_key_missing`, `bib.duplicate_entry`, `bib.missing_required_field`, `bib.missing_doi`, `bib.uncited_entry`.

- [ ] **Step 1: Write the failing tests**

```python
_BIB = """@article{ok, title={T}, author={A}, journal={J}, year={2020}, doi={10.1/x}}"""

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
    bib = ("@article{a, title={One}, doi={10.1/x}, journal={J}, year={2020}}\n"
           "@article{b, title={Two}, doi={10.1/X}, journal={J}, year={2021}}")
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\\cite{b}\n"}), bib)
    assert "bib.duplicate_entry" in [f.rule for f in out]

def test_entry_without_doi_or_eprint_is_info():
    bib = "@book{b, title={T}, author={A}, publisher={P}, year={2020}}"
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{b}\n"}), bib)
    assert "bib.missing_doi" in [f.rule for f in out]

def test_no_bib_content_reports_nothing_rather_than_everything():
    out = check_bibliography(build_source("main.tex", {"main.tex": "\\cite{a}\n"}), "")
    assert out == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_bibliography.py -v`
Expected: FAIL — `check_bibliography` undefined

- [ ] **Step 3: Implement the module**

`collect_cite_keys` calls the existing `extract_cite_keys` on each masked file — reusing the repo's regex while the masking removes the commented-out `\cite` it would otherwise collect — then unions a module-level regex for the capitalized natbib forms `\Cite`, `\Citep`, `\Citet`, `\Citeauthor`, `\Citeyear`, which `CITE_RE` cannot match (spec §4.4). Do not modify `CITE_RE`.

Parse the bibliography with the existing `parse_bib_entries`; an empty parse result means "no bibliography supplied", which must emit nothing at all rather than flagging every citation. Required fields per type: `@article` → `journal`, `year`; `@inproceedings`/`@conference` → `booktitle`, `year`; `@book` → `publisher`, `year`; `@phdthesis`/`@mastersthesis` → `school`, `year`; every type → `title`. Duplicates: group by lowercased `doi` when present, else by `normalize_title` from `src/services/citations/title_match.py`. Suppress `bib.uncited_entry` when `src.unresolved_includes` is non-empty, for the same reason as Task 3.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_bibliography.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/rules/bibliography.py tests/test_preflight/test_bibliography.py
git commit -m "feat(preflight): bibliography hygiene rules"
```

---

### Task 5: Required-statement rules

**Files:**
- Create: `src/services/preflight/rules/statements.py`
- Create: `tests/test_preflight/test_statements.py`

**Interfaces:**
- Consumes: `PreflightSource` (Task 1), `Finding` (Task 2), `PreflightProfile` (Task 2).
- Produces: `def check_statements(src: PreflightSource, required: Sequence[str]) -> list[Finding]` — emits `statement.<name>_missing` for each requested statement it cannot find.

- [ ] **Step 1: Write the failing tests**

```python
_ALL = ["data_availability", "ethics", "coi", "funding", "author_contributions"]

def test_empty_paper_misses_every_requested_statement():
    out = check_statements(build_source("main.tex", {"main.tex": "Text.\n"}), _ALL)
    assert len(out) == 5

def test_a_heading_satisfies_the_statement():
    doc = "\\section{Data Availability}\nOn request.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"])
    assert out == []

def test_an_inline_phrase_satisfies_the_statement():
    doc = "The data supporting the findings are available upon request.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["data_availability"])
    assert out == []

def test_vietnamese_heading_is_recognised():
    doc = "\\section{Xung đột lợi ích}\nKhông có.\n"
    out = check_statements(build_source("main.tex", {"main.tex": doc}), ["coi"])
    assert out == []

def test_a_statement_in_an_included_file_counts():
    files = {"main.tex": "\\input{back}\n", "back.tex": "\\section{Funding}\nNSF.\n"}
    assert check_statements(build_source("main.tex", files), ["funding"]) == []

def test_only_requested_statements_are_checked():
    out = check_statements(build_source("main.tex", {"main.tex": "Text.\n"}), ["ethics"])
    assert [f.rule for f in out] == ["statement.ethics_missing"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_statements.py -v`
Expected: FAIL — `check_statements` undefined

- [ ] **Step 3: Implement the module**

One module-level table maps each statement name to a heading pattern and a phrase pattern, each covering EN and VI (the repo's audience is bilingual — `logic_audit/language.py` and `parse_latex_sections`' alias table are the precedent for carrying both). Search every masked file: a statement is satisfied when either pattern matches anywhere. Match case-insensitively; VI patterns must tolerate the unaccented spellings the repo already handles elsewhere (`tóm tắt` / `tom tat`).

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_statements.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/rules/statements.py tests/test_preflight/test_statements.py
git commit -m "feat(preflight): required submission-statement rules"
```

---

### Task 6: Formatting-manipulation rules

**Files:**
- Create: `src/services/preflight/rules/formatting.py`
- Create: `tests/test_preflight/test_formatting.py`

**Interfaces:**
- Consumes: `PreflightSource` (Task 1), `Finding` (Task 2).
- Produces: `def check_formatting(src: PreflightSource) -> list[Finding]` — emits `format.compressed_leading`, `format.margin_override`, `format.large_negative_vspace`, `format.font_size_override`.

- [ ] **Step 1: Write the failing tests**

```python
def _f(doc):
    return [x.rule for x in check_formatting(build_source("main.tex", {"main.tex": doc}))]

def test_leading_below_one_is_critical():
    assert "format.compressed_leading" in _f("\\linespread{0.92}\n")

def test_leading_at_or_above_one_is_fine():
    assert _f("\\linespread{1.0}\n") == []

def test_setstretch_and_baselinestretch_are_covered():
    assert "format.compressed_leading" in _f("\\setstretch{0.95}\n")
    assert "format.compressed_leading" in _f("\\renewcommand{\\baselinestretch}{0.9}\n")

def test_linespread_inside_a_listing_is_not_a_finding():
    doc = "\\begin{verbatim}\n\\linespread{0.8}\n\\end{verbatim}\n"
    assert _f(doc) == []

def test_margin_override_only_matters_for_a_venue_class():
    assert "format.margin_override" not in _f(
        "\\documentclass{article}\n\\usepackage[margin=1in]{geometry}\n"
    )
    assert "format.margin_override" in _f(
        "\\documentclass{IEEEtran}\n\\usepackage[margin=1in]{geometry}\n"
    )

def test_large_negative_vspace_is_counted_once_with_its_total():
    out = check_formatting(build_source("main.tex", {
        "main.tex": "\\vspace{-1em}\n\\vspace{-2em}\n\\vspace{-2pt}\n"}))
    hit = [f for f in out if f.rule == "format.large_negative_vspace"]
    assert len(hit) == 1 and hit[0].count == 2      # -2pt is small, not counted
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_formatting.py -v`
Expected: FAIL — `check_formatting` undefined

- [ ] **Step 3: Implement the module**

Read the declared class from `\documentclass[...]{name}`. `format.margin_override` fires only when the class is **not** one of `article`, `report`, `book`, `memoir`, `scrartcl` — with a plain class, changing margins is ordinary, and flagging it would be the plan's most likely false positive. Negative `vspace` counts as "large" at ≥ 1em or ≥ 12pt; report a single finding carrying the number of occurrences in `count`, at the first offending line.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_formatting.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/rules/formatting.py tests/test_preflight/test_formatting.py
git commit -m "feat(preflight): formatting-manipulation rules"
```

---

### Task 7: Anonymity rules

**Files:**
- Create: `src/services/preflight/rules/anonymity.py`
- Create: `tests/test_preflight/test_anonymity.py`

**Interfaces:**
- Consumes: `PreflightSource` (Task 1), `Finding` (Task 2).
- Produces: `def check_anonymity(src: PreflightSource) -> list[Finding]` — emits the nine `anon.*` rules from spec §3.5. The caller runs it only when `profile.double_blind` is true; the function itself does not read the profile.

- [ ] **Step 1: Write the failing tests**

```python
def _a(doc):
    return [x.rule for x in check_anonymity(build_source("main.tex", {"main.tex": doc}))]

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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_anonymity.py -v`
Expected: FAIL — `check_anonymity` undefined

- [ ] **Step 3: Implement the module**

A module-level `frozenset` of placeholder author values (`anonymous`, `anonymous author`, `anonymous authors`, `anon.`, empty) decides whether `\author`/`\institute`/`\affiliation`/`\affil` counts as populated; compare case-insensitively after stripping LaTeX markup and whitespace. Keep the grant-number regex narrow — a bare four-digit year must not match, or every paper with a date fires this rule.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_anonymity.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/rules/anonymity.py tests/test_preflight/test_anonymity.py
git commit -m "feat(preflight): double-blind anonymity rules"
```

---

### Task 8: Length rule

**Files:**
- Create: `src/services/preflight/rules/length.py`
- Create: `tests/test_preflight/test_length.py`

**Interfaces:**
- Consumes: `PreflightSource` (Task 1), `Finding` (Task 2).
- Produces:
  ```python
  def count_body_words(src: PreflightSource) -> int
  def check_length(src: PreflightSource, word_limit: int) -> list[Finding]
  ```
  Emits `length.over_limit`, `length.near_limit`.

- [ ] **Step 1: Write the failing tests**

```python
def _src(doc):
    return build_source("main.tex", {"main.tex": doc})

def test_preamble_and_comments_are_not_counted():
    doc = "\\documentclass{article}\n\\begin{document}\n% ignored words here\nOne two three.\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 3

def test_math_is_not_counted_but_captions_are():
    doc = "\\begin{document}\nValue $x + y = z$ holds.\n\\caption{Two words}\n\\end{document}\n"
    assert count_body_words(_src(doc)) == 4          # Value, holds, Two, words

def test_included_file_words_are_counted():
    files = {"main.tex": "\\begin{document}\n\\input{a}\n\\end{document}\n", "a.tex": "one two\n"}
    assert count_body_words(build_source("main.tex", files)) == 2

def test_over_limit_is_critical_and_carries_the_count():
    doc = "\\begin{document}\n" + "word " * 50 + "\n\\end{document}\n"
    out = check_length(_src(doc), 10)
    assert [(f.rule, f.count) for f in out] == [("length.over_limit", 50)]

def test_just_under_the_limit_warns_near():
    doc = "\\begin{document}\n" + "word " * 98 + "\n\\end{document}\n"
    assert [f.rule for f in check_length(_src(doc), 100)] == ["length.near_limit"]

def test_comfortably_under_the_limit_is_silent():
    doc = "\\begin{document}\nword\n\\end{document}\n"
    assert check_length(_src(doc), 100) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_length.py -v`
Expected: FAIL — `count_body_words` undefined

- [ ] **Step 3: Implement the module**

There is no reusable word counter in the repo, so this is net-new. Take the body between `\begin{document}` and `\end{document}` (the whole masked text when those are absent — an `\input`ed fragment has no document environment), drop `$…$`, `$$…$$`, `\(…\)`, `\[…\]` and the `equation`/`align` environments, drop the `\bibliography`/`\printbibliography` tail, then convert to plain text with `LatexNodes2Text` from pylatexenc (already a dependency, used in `citations/title_match.py:13`) and count whitespace-separated tokens. `near_limit` fires from 95% up to and including the limit; `over_limit` fires above it. Both carry the measured count in `count`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_length.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/rules/length.py tests/test_preflight/test_length.py
git commit -m "feat(preflight): word-count limit rule"
```

---

### Task 9: Runner

**Files:**
- Create: `src/services/preflight/runner.py`
- Create: `tests/test_preflight/test_runner.py`

**Interfaces:**
- Consumes: every `check_*` function (Tasks 3–8), `build_source` (Task 1), `catalogue` + schemas (Task 2).
- Produces: `def run_preflight(request: PreflightRequest) -> PreflightReport` — the only entry point the API layer calls. Sync `def`: it is pure CPU over in-memory strings.

- [ ] **Step 1: Write the failing tests**

```python
def _req(doc="Text.\n", **kw):
    kw.setdefault("files", [PreflightFile(path="main.tex", content=doc)])
    return PreflightRequest(main_file="main.tex", **kw)

def test_report_is_advisory_and_counts_by_severity():
    rep = run_preflight(_req("\\ref{ghost}\n"))
    assert rep.integrity_mode == "comment_only"
    assert rep.counts["critical"] == 1

def test_findings_carry_stable_unique_ids():
    rep = run_preflight(_req("\\ref{a}\n\\ref{b}\n"))
    ids = [f.id for f in rep.findings]
    assert len(set(ids)) == len(ids)
    assert all(f.id.startswith(f.rule + ":") for f in rep.findings)

def test_undeclared_groups_are_skipped_not_silently_passed():
    rep = run_preflight(_req())
    assert set(rep.skipped) == {"anon", "length"}

def test_double_blind_suppresses_the_funding_statement_rule():
    rep = run_preflight(_req(profile=PreflightProfile(
        double_blind=True, required_statements=["funding", "author_contributions"])))
    assert "statement.funding_missing" in rep.suppressed
    assert "statement.funding_missing" not in [f.rule for f in rep.findings]

def test_unresolved_includes_suppress_the_cross_file_rules():
    rep = run_preflight(_req("\\input{missing}\n\\ref{ghost}\n"))
    assert rep.unresolved_includes == ["missing.tex"]
    assert "crossref.undefined_ref" in rep.suppressed
    assert "crossref.undefined_ref" not in [f.rule for f in rep.findings]

def test_every_emitted_rule_is_registered_in_the_catalogue():
    doc = "\\documentclass{IEEEtran}\n\\author{Jane Doe}\n\\linespread{0.9}\n\\ref{x}\n\\label{y}\n"
    rep = run_preflight(_req(doc, bib_content="@article{a, title={T}}",
                             profile=PreflightProfile(double_blind=True, word_limit=5)))
    assert rep.findings
    for f in rep.findings:
        assert f.rule in PREFLIGHT_RULE_IDS

def test_findings_are_ordered_critical_first():
    doc = "\\label{unused}\n\\ref{ghost}\n"
    sev = [f.severity for f in run_preflight(_req(doc)).findings]
    assert sev == sorted(sev, key=["critical", "warning", "info"].index)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_runner.py -v`
Expected: FAIL — `run_preflight` undefined

- [ ] **Step 3: Implement `run_preflight`**

Build the source, run each group, then assemble. Groups not declared in the profile go to `skipped` (`anon` without `double_blind`, `length` without `word_limit`) — a skipped group must be reported, never silently treated as passing. Suppressions are collected in one place: the double-blind funding/author-contributions conflict from spec §3.5, and the cross-file rules when `unresolved_includes` is non-empty. Assign `f"{rule}:{n}"` ids by per-rule ordinal, set `severity` from `RULE_SEVERITY`, sort critical → warning → info keeping each group's internal order, and drop any finding whose `line` exceeds its file's line count.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_preflight/ -v`
Expected: PASS (all tasks 1–9)

- [ ] **Step 5: Commit**

```bash
git add src/services/preflight/runner.py tests/test_preflight/test_runner.py
git commit -m "feat(preflight): runner with skip and suppression bookkeeping"
```

---

### Task 10: API endpoint

**Files:**
- Create: `src/api/preflight_routes.py`
- Modify: `src/main.py` (one import in the alphabetical block at lines 8-20; one `include_router` inside the `prefix="/api/v1"` block that ends at line 107)
- Create: `tests/test_preflight/test_api.py`

**Interfaces:**
- Consumes: `run_preflight` (Task 9), `PreflightRequest`/`PreflightReport` (Task 2).
- Produces: `POST /api/v1/preflight/run`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_run_returns_a_report(client):
    res = await client.post("/api/v1/preflight/run", json={
        "main_file": "main.tex",
        "files": [{"path": "main.tex", "content": "See \\ref{ghost}.\n"}],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["integrity_mode"] == "comment_only"
    assert body["findings"][0]["rule"] == "crossref.undefined_ref"

@pytest.mark.asyncio
async def test_unsafe_main_file_is_rejected(client):
    res = await client.post("/api/v1/preflight/run", json={
        "main_file": "../../etc/passwd", "files": []})
    assert res.status_code == 422

@pytest.mark.asyncio
async def test_too_many_files_is_rejected(client):
    files = [{"path": f"f{i}.tex", "content": ""} for i in range(65)]
    res = await client.post("/api/v1/preflight/run", json={"files": files})
    assert res.status_code == 422

@pytest.mark.asyncio
async def test_empty_payload_reports_nothing_rather_than_erroring(client):
    res = await client.post("/api/v1/preflight/run", json={"files": []})
    assert res.status_code == 200
    assert res.json()["findings"] == []
```

Note for the implementer: the default suite strips `DATABASE_URL` before importing the app (`tests/conftest.py:12-16`), so `db_is_ready()` is False and nothing is authenticated. These tests therefore prove the *contract*, not the auth gate — do not add a test here claiming to prove rejection of an anonymous caller, because it would pass for the wrong reason.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_preflight/test_api.py -v`
Expected: FAIL — 404, route not mounted

- [ ] **Step 3: Implement the route and mount it**

Module docstring, then `from __future__ import annotations`. `router = APIRouter(prefix="/preflight", tags=["preflight"])`; the handler is `@router.post("/run", response_model=PreflightReport)` with `user: User = Depends(get_current_user)` and a plain `def`. The body is one call to `run_preflight(request)` — no session store, no DB read, no quota call. In `src/main.py` the import block is alphabetical and enforced by ruff `I`, while the mount order is not alphabetical; get both right or CI fails.

- [ ] **Step 4: Run the whole backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 778 pre-existing tests plus the new ones, 0 failures

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests
git add src/api/preflight_routes.py src/main.py tests/test_preflight/test_api.py
git commit -m "feat(preflight): POST /api/v1/preflight/run"
```

---

### Task 11: Frontend API client and bilingual rule copy

**Files:**
- Create: `frontend/src/lib/api/preflight-api.ts`
- Create: `frontend/src/lib/preflight-i18n.ts`
- Create: `frontend/src/lib/preflight-i18n.test.ts`
- Create: `tests/test_preflight/test_catalogue_parity.py`

**Interfaces:**
- Consumes: the endpoint from Task 10.
- Produces:
  ```ts
  // preflight-api.ts
  export type PreflightRuleId = "crossref.undefined_ref" | ... ;   // all 29, mirrors PREFLIGHT_RULE_IDS
  export type PreflightSeverity = "critical" | "warning" | "info";
  export type PreflightFinding = {
    id: string; rule: PreflightRuleId; group: string; severity: PreflightSeverity;
    file: string; line: number | null; symbol: string; count: number; excerpt: string;
  };
  export type PreflightReport = {
    integrity_mode: string; findings: PreflightFinding[]; counts: Record<string, number>;
    skipped: string[]; suppressed: string[]; unresolved_includes: string[];
  };
  export type PreflightProfileInput = {
    doubleBlind: boolean; wordLimit: number | null; requiredStatements: string[];
  };
  export async function runPreflight(opts: {
    mainFile: string; files: { path: string; content: string }[];
    bibContent?: string; profile: PreflightProfileInput;
    locale?: UiLanguage; signal?: AbortSignal;
  }): Promise<PreflightReport>;

  // preflight-i18n.ts
  export type PreflightRuleCopy = { title: string; hint: string };
  export type PreflightCopy = {
    tab: string; run: string; running: string; clean: string; approximate: string;
    goToLine: string; severity: Record<PreflightSeverity, string>;
    rules: Record<PreflightRuleId, PreflightRuleCopy>;
  };
  export function preflightCopy(locale: UiLanguage): PreflightCopy;
  ```
  `rules: Record<PreflightRuleId, …>` inside a `const COPY: Record<UiLanguage, PreflightCopy>` is what makes a missing translation a `npm run typecheck` failure rather than a blank row in the panel.

- [ ] **Step 1: Write the failing tests**

```ts
// preflight-i18n.test.ts
import { describe, expect, it } from "vitest";
import { preflightCopy } from "./preflight-i18n";

describe("preflightCopy", () => {
  it("gives every rule a non-empty title and hint in both locales", () => {
    for (const locale of ["en", "vi"] as const) {
      const copy = preflightCopy(locale);
      for (const [rule, text] of Object.entries(copy.rules)) {
        expect(text.title.trim(), `${locale}/${rule} title`).not.toBe("");
        expect(text.hint.trim(), `${locale}/${rule} hint`).not.toBe("");
      }
    }
  });

  it("does not leave Vietnamese copy identical to English", () => {
    const en = preflightCopy("en");
    const vi = preflightCopy("vi");
    const same = Object.keys(en.rules).filter(
      (r) => en.rules[r as keyof typeof en.rules].title === vi.rules[r as keyof typeof vi.rules].title,
    );
    expect(same).toEqual([]);
  });

  it("says the word count is approximate", () => {
    expect(preflightCopy("en").approximate.trim()).not.toBe("");
    expect(preflightCopy("vi").approximate.trim()).not.toBe("");
  });
});
```

```python
# tests/test_preflight/test_catalogue_parity.py
_TS = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/lib/api/preflight-api.ts"

def test_the_typescript_union_matches_the_python_catalogue():
    text = _TS.read_text(encoding="utf-8")
    union = set(re.findall(r'"((?:crossref|bib|statement|format|anon|length)\.[a-z_]+)"', text))
    assert union == set(PREFLIGHT_RULE_IDS)
```

- [ ] **Step 2: Run both to verify they fail**

Run: `cd frontend && npx vitest run src/lib/preflight-i18n.test.ts`
Expected: FAIL — cannot resolve `./preflight-i18n`
Run: `.venv/bin/python -m pytest tests/test_preflight/test_catalogue_parity.py -v`
Expected: FAIL — `preflight-api.ts` does not exist

- [ ] **Step 3: Implement both modules**

`preflight-api.ts` follows `citation-relevance-api.ts` exactly: `resolveApiBase()` at module scope, a local `authHeaders()`, and in the `catch` the `AbortError` re-throw **first**, then `throw new Error("NETWORK_ERROR", { cause: error })` — that string is a load-bearing sentinel compared lowercased in `api-errors.ts:34-44`, so any other wording degrades the user-facing message. `logoutUser()` on 401, `mapApiHttpErrorFromResponse(res, locale)` on any other failure. JSON body keys are snake_case (`main_file`, `bib_content`, `word_limit`, `double_blind`, `required_statements`) — camelCase yields a 422. Do not import `apiFetch` from `academic.ts`; it is not exported.

`preflight-i18n.ts` uses the `peer-review-i18n.ts` shape: `const COPY: Record<UiLanguage, PreflightCopy>` plus the accessor. Write real Vietnamese for all 29 rules, not copied English. The `approximate` string must state plainly that the word count is an estimate and each venue counts differently — spec §3.6 makes this a requirement, not a nicety.

- [ ] **Step 4: Run both to verify they pass**

Run: `cd frontend && npx vitest run src/lib/preflight-i18n.test.ts && npm run typecheck`
Expected: PASS, 0 type errors
Run: `.venv/bin/python -m pytest tests/test_preflight/test_catalogue_parity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api/preflight-api.ts frontend/src/lib/preflight-i18n.ts frontend/src/lib/preflight-i18n.test.ts tests/test_preflight/test_catalogue_parity.py
git commit -m "feat(preflight): API client and bilingual rule copy"
```

---

### Task 12: Panel, state hook, and tab wiring

**Files:**
- Create: `frontend/src/features/editor/state/useEditorPreflight.ts`
- Create: `frontend/src/features/editor/components/PreflightPanel.tsx`
- Modify: `frontend/src/features/editor/types.ts:36`
- Modify: `frontend/src/features/editor/components/ToolsPanel.tsx` (tab list 154-163; a render branch before the fallback at 340; props literal 53-85)
- Modify: `frontend/src/features/editor/components/MobileToolsSheet.tsx` (destructure 10-41, type literal 42-74, forward list 92-124 — all three)
- Modify: `frontend/src/features/editor/EditorWorkspace.tsx` (instantiate the hook, add its props to `toolsPanelBindings`)
- Modify: `frontend/src/styles.css` (classes under the `.editor-shell` ancestor)

**Interfaces:**
- Consumes: `runPreflight`, `preflightCopy` (Task 11).
- Produces: `export function useEditorPreflight(opts: UseEditorPreflightOptions)` returning `{ report, loading, error, runPreflight, profile, setProfile, jumpToFinding, canJumpToFinding }`, and `<PreflightPanel />`.

- [ ] **Step 1: Widen the union and add the tab**

`types.ts:36` — append `| "preflight"`. In `ToolsPanel.tsx` add `{ id: "preflight" as const, label: preflightCopy(locale).tab },` to the tab list: the per-element `as const` is required, because without it `item.id` widens to `string` and `setTab(item.id)` fails typecheck.

- [ ] **Step 2: Add the render branch BEFORE the fallback**

Insert `) : tab === "preflight" ? (` ahead of the bare `) : (` at `ToolsPanel.tsx:340`. That fallback is the Versions view and there is no `tab === "versions"` branch, so a new union member without its own branch silently renders revision history and TypeScript does not complain. Verify by opening the tab, not by reading the diff.

- [ ] **Step 3: Implement the hook**

Match `useEditorTools.ts`: `const t = useMemo(() => preflightCopy(locale), [locale])` first, then a flat `useState` block (`report`, `loading`, `error`), then a `useRef<AbortController | null>(null)` for the in-flight run. The hook receives the project's files, `mainFile`, `activeFile`, `switchActiveFile`, and `jumpToOutlineLine` from the caller — never re-derive them. `jumpToFinding(finding)` calls `switchActiveFile(finding.file)` before `jumpToOutlineLine(finding.line)`, because panel line numbers are computed per file while the editor renders the active buffer (`useEditorTools.ts:343` is the precedent). `canJumpToFinding` checks `finding.line != null && finding.line >= 1 && finding.line <= lineCount(finding.file)`: `scrollToLineInternal` only guards `line < 1` (`latex-code-editor.tsx:260`) and does not clamp past EOF. Do **not** add an effect that auto-switches the active tab when a report arrives — the two effects at `ToolsPanel.tsx:99-109` already yank the user to Logic and Structure, and a third would make the strip unusable.

Persist the declared profile per paper in `localStorage`; no DB column in v1.

- [ ] **Step 4: Implement the panel**

`PreflightPanel.tsx` exports only the component (Fast Refresh). House markup: `<div className="tools-section">` + `<h2 className="tools-section-title">`. It renders the profile form (double-blind toggle, optional word limit, statement checkboxes), a run button, then findings grouped critical → warning → info, each row carrying the rule title, the offending `symbol`, and a go-to-line button gated on `canJumpToFinding`. Show `skipped` groups and `suppressed` rules explicitly with their reason — a group that did not run must never look like a group that passed. Display the `approximate` note next to any `length.*` finding. When `findings` is empty, state that this is a mechanical check and does not replace the venue's CFP.

New CSS goes under the `.editor-shell` ancestor (`styles.css` 6977+); a class without it will not apply.

- [ ] **Step 5: Handle the fresh-template case**

Spec §7 requires it: a paper just created from a template is all `% TODO` placeholders with no
bibliography, so a plain run buries the author under findings on a document they have not written
yet. Reuse the existing signal rather than inventing one — `assessManuscriptMaturity(latex)` in
`frontend/src/lib/paper-score.ts:103` returns `{ isPlaceholderTemplate, bodyWordCount }`. When it
reports a placeholder template, the panel says the draft is still a skeleton and offers the run
behind an explicit click instead of listing findings. Add a case to
`frontend/src/lib/preflight-i18n.test.ts` asserting that copy exists in both locales.

- [ ] **Step 6: Wire EditorWorkspace and the mobile sheet**

Instantiate the hook and add its props to `toolsPanelBindings`, extending that `useMemo`'s hand-written dependency array — a member added to the object but not the deps closes over a stale `mainLatexSource`. `MobileToolsSheet.tsx` has no spread: add each new prop in all three blocks. Omitting the forward list compiles cleanly and leaves the prop permanently undefined on mobile.

- [ ] **Step 7: Verify the whole frontend**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: 0 type errors, clean lint, 198 pre-existing tests plus the new ones passing

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat(preflight): Tools panel tab, state hook, and mobile wiring"
```

---

### Task 13: Full verification and documentation

**Files:**
- Modify: `ROADMAP.md` (§2 status table and §9 next-steps list)
- Modify: `CLAUDE.md` (architecture map: one line for `src/services/preflight/`)

- [ ] **Step 1: Run the gate CI runs**

Run: `.venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests && .venv/bin/python -m pytest tests/ -q`
Expected: clean lint, all tests pass
Run: `cd frontend && npm run lint -- --max-warnings 0 && npm run typecheck && npm test && npm run build`
Expected: all clean

- [ ] **Step 2: Exercise the feature in the running app**

Start the backend and the Vite dev server, open a multi-file project, and confirm by observation: the Preflight tab renders its own panel and not the revision history; a finding in an `\input`ed file jumps to the right file and line; a document with a missing `\input` reports the suppression instead of a wall of criticals.

- [ ] **Step 3: Update the docs**

In `ROADMAP.md`, add Submission Preflight to the completed table in §2 and remove nothing from §9 that is still outstanding. In `CLAUDE.md`, add `src/services/preflight/` to the architecture map in the established one-line style. Docs are Vietnamese with English technical terms.

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md CLAUDE.md
git commit -m "docs(preflight): record the Submission Preflight panel"
```
