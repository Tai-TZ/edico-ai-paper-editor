import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_PREFLIGHT_PROFILE,
  PREFLIGHT_WORD_LIMIT_MAX,
  canJumpToPreflightFinding,
  collectPreflightBibContent,
  loadPreflightProfile,
  preflightCrossFileCauseFiles,
  preflightCrossFileCauses,
  preflightLineCount,
  preflightSuppressionReason,
  sanitizeWordLimitInput,
  savePreflightProfile,
} from "./preflight-panel";
import type { PreflightFinding } from "@/lib/api/preflight-api";

function finding(overrides: Partial<PreflightFinding> = {}): PreflightFinding {
  return {
    id: "crossref.undefined_ref:0",
    rule: "crossref.undefined_ref",
    group: "crossref",
    severity: "critical",
    file: "main.tex",
    line: 3,
    symbol: "fig:pipeline",
    count: 1,
    excerpt: "",
    ...overrides,
  };
}

describe("preflightLineCount", () => {
  it("counts lines the same way for LF and CRLF content", () => {
    expect(preflightLineCount("a\nb\nc")).toBe(3);
    expect(preflightLineCount("a\r\nb\r\nc")).toBe(3);
  });

  it("never returns 0, even for an empty file", () => {
    expect(preflightLineCount("")).toBe(1);
  });
});

describe("canJumpToPreflightFinding", () => {
  const files = [
    { path: "main.tex", content: "line1\nline2\nline3" },
    { path: "sections/intro.tex", content: "only one line" },
  ];

  it("allows a line within the file's real range", () => {
    expect(canJumpToPreflightFinding(finding({ file: "main.tex", line: 3 }), files)).toBe(true);
  });

  it("rejects a line past end-of-file instead of silently scrolling to the bottom", () => {
    // scrollToLineInternal only guards `line < 1` and does not clamp past EOF — this is the
    // bounds check that stands in for that missing clamp.
    expect(canJumpToPreflightFinding(finding({ file: "main.tex", line: 4 }), files)).toBe(false);
  });

  it("rejects a null line", () => {
    expect(canJumpToPreflightFinding(finding({ file: "main.tex", line: null }), files)).toBe(false);
  });

  it("rejects line 0 and negative lines", () => {
    expect(canJumpToPreflightFinding(finding({ file: "main.tex", line: 0 }), files)).toBe(false);
    expect(canJumpToPreflightFinding(finding({ file: "main.tex", line: -1 }), files)).toBe(false);
  });

  it("rejects a finding whose file isn't in the known file list", () => {
    expect(
      canJumpToPreflightFinding(finding({ file: "sections/missing.tex", line: 1 }), files),
    ).toBe(false);
  });

  it("allows the single line of a one-line file", () => {
    expect(canJumpToPreflightFinding(finding({ file: "sections/intro.tex", line: 1 }), files)).toBe(
      true,
    );
  });

  it("rejects a line beyond its OWN file's length even though it's within another file's length", () => {
    // main.tex has 3 lines; sections/intro.tex has only 1. Line 2 is past intro.tex's own EOF but
    // still inside main.tex's range — a mutant that counts lines off `files[0]` (main.tex)
    // instead of the finding's own file, or that bounds against the longest file in the project,
    // would both incorrectly say `true` here. Only checking the finding's own file catches it.
    expect(canJumpToPreflightFinding(finding({ file: "sections/intro.tex", line: 2 }), files)).toBe(
      false,
    );
  });
});

describe("preflightSuppressionReason", () => {
  // The exact four rule ids `runner.py` ever suppresses — `_CROSS_FILE_SUPPRESSED_RULES` and
  // `_DOUBLE_BLIND_SUPPRESSED_RULES` (src/services/preflight/runner.py:68-74), listed verbatim so
  // this test breaks the moment either list in the backend drifts from this one.
  const BACKEND_SUPPRESSIBLE_RULES: Record<
    string,
    "unresolved_includes" | "double_blind_conflict"
  > = {
    "crossref.undefined_ref": "unresolved_includes",
    "bib.uncited_entry": "unresolved_includes",
    "statement.funding_missing": "double_blind_conflict",
    "statement.author_contributions_missing": "double_blind_conflict",
  };

  it("maps each of the backend's four suppressible rule ids to the reason runner.py suppresses it for", () => {
    for (const [rule, expected] of Object.entries(BACKEND_SUPPRESSIBLE_RULES)) {
      expect(preflightSuppressionReason(rule)).toBe(expected);
    }
  });

  it("pins the chosen partition direction, not the mirror-image one", () => {
    // Over the four ids above, today's real partition ("crossref./bib. -> unresolved_includes,
    // else -> double_blind_conflict") and a mirror-image partition ("statement. ->
    // double_blind_conflict, else -> unresolved_includes") produce IDENTICAL results, because
    // every id above happens to land on the side both partitions agree on — so the test above
    // alone cannot tell the two apart. A rule id from neither family breaks the tie: today's
    // "else" branch answers double_blind_conflict, the mirror's answers unresolved_includes.
    // This pins today's actual direction so a regression (or a mutation test) that silently
    // flips it gets caught — independent of which family's ids happen to be exercised above.
    expect(preflightSuppressionReason("format.compressed_leading")).toBe("double_blind_conflict");
  });
});

// vitest.config.ts runs `environment: "node"` — there is no real `localStorage` global, so
// preflight-panel.ts reads/writes the bare `localStorage` global (not `window.localStorage`,
// which doesn't exist here either) and the test stubs it in, the same way auth-store.test.ts
// stubs it for auth-store.ts's own bare `localStorage` access.
class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  clear() {
    this.data.clear();
  }
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  key(index: number) {
    return Array.from(this.data.keys())[index] ?? null;
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
  setItem(key: string, value: string) {
    this.data.set(key, String(value));
  }
}

describe("preflight profile persistence", () => {
  const paperId = "paper-123";
  let store: MemoryStorage;

  beforeEach(() => {
    store = new MemoryStorage();
    vi.stubGlobal("localStorage", store);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the default profile when nothing was ever saved", () => {
    // Asserted against the literal expected value, not `DEFAULT_PREFLIGHT_PROFILE` itself — that
    // would compare the constant to itself and stay green even if `DEFAULT_PREFLIGHT_PROFILE`
    // drifted from the backend default it's supposed to mirror
    // (src/models/preflight_schemas.py:28-30: `double_blind: bool = False`,
    // `word_limit: int | None = None`, `required_statements` defaulting to exactly these four, in
    // this order).
    expect(loadPreflightProfile(paperId)).toEqual({
      doubleBlind: false,
      wordLimit: null,
      requiredStatements: ["data_availability", "ethics", "coi", "funding"],
    });
  });

  it("rejects a persisted wordLimit of 0 and falls back to null", () => {
    // `parsed.wordLimit > 0` guards this; a relaxation to `>= 0` would let a stored 0 through,
    // and a backend whose schema is `ge=1` would reject it outright.
    store.setItem(`edico-preflight-profile:${paperId}`, JSON.stringify({ wordLimit: 0 }));
    expect(loadPreflightProfile(paperId).wordLimit).toBeNull();
  });

  it("round-trips a saved profile exactly", () => {
    const profile = { doubleBlind: true, wordLimit: 8000, requiredStatements: ["ethics"] };
    savePreflightProfile(paperId, profile);
    expect(loadPreflightProfile(paperId)).toEqual(profile);
  });

  it("falls back to the default on malformed stored JSON instead of throwing", () => {
    store.setItem(`edico-preflight-profile:${paperId}`, "{not json");
    expect(loadPreflightProfile(paperId)).toEqual(DEFAULT_PREFLIGHT_PROFILE);
  });

  it("never touches localStorage for an empty paperId (unsaved project)", () => {
    savePreflightProfile("", { doubleBlind: true, wordLimit: 1, requiredStatements: [] });
    expect(store.length).toBe(0);
    expect(loadPreflightProfile("")).toEqual(DEFAULT_PREFLIGHT_PROFILE);
  });

  it("keeps two papers' profiles independent", () => {
    savePreflightProfile("paper-a", { doubleBlind: true, wordLimit: null, requiredStatements: [] });
    savePreflightProfile("paper-b", {
      doubleBlind: false,
      wordLimit: 500,
      requiredStatements: ["coi"],
    });
    expect(loadPreflightProfile("paper-a").doubleBlind).toBe(true);
    expect(loadPreflightProfile("paper-b").wordLimit).toBe(500);
  });
});

describe("sanitizeWordLimitInput", () => {
  it("clears the limit on empty or whitespace-only input", () => {
    expect(sanitizeWordLimitInput("")).toBeNull();
    expect(sanitizeWordLimitInput("   ")).toBeNull();
  });

  it("floors fractional input and clamps up to at least 1", () => {
    expect(sanitizeWordLimitInput("3.7")).toBe(3);
    expect(sanitizeWordLimitInput("0")).toBe(1);
    expect(sanitizeWordLimitInput("-5")).toBe(1);
  });

  it("clamps to the backend's upper bound instead of passing an oversized value through", () => {
    // PreflightProfile.word_limit is `Field(ge=1, le=100_000)` (src/models/preflight_schemas.py:29).
    // Without this clamp, typing e.g. 200000 reaches the backend and comes back as a generic 422
    // error banner instead of being caught here as a field-level bound.
    expect(sanitizeWordLimitInput(String(PREFLIGHT_WORD_LIMIT_MAX + 1))).toBe(
      PREFLIGHT_WORD_LIMIT_MAX,
    );
    expect(sanitizeWordLimitInput(String(PREFLIGHT_WORD_LIMIT_MAX))).toBe(PREFLIGHT_WORD_LIMIT_MAX);
  });

  it("falls back to null for non-numeric input instead of persisting NaN", () => {
    expect(sanitizeWordLimitInput("abc")).toBeNull();
  });
});

// --- final whole-branch review, FIX 2: every .bib, not the first one ---------------------------

describe("collectPreflightBibContent", () => {
  const files = [
    { path: "main.tex", content: "\\cite{lee2022} \\cite{kim2023}" },
    { path: "refs.bib", content: "@article{lee2022, title={A}}" },
    { path: "extra.bib", content: "@inproceedings{kim2023, title={B}}" },
  ];

  it("includes every .bib file, not just the first in array order", () => {
    // The bug this replaces: `projectFiles.find(isBibFile)` kept refs.bib and silently dropped
    // extra.bib, so every key defined in extra.bib came back as `bib.cite_key_missing` at
    // `critical` on a correct paper. Measured: 1 false critical with either file alone, 0 with
    // both.
    const bib = collectPreflightBibContent(files);
    expect(bib).toContain("lee2022");
    expect(bib).toContain("kim2023");
  });

  it("joins the files with a newline so two entries never fuse into one", () => {
    const bib = collectPreflightBibContent([
      { path: "a.bib", content: "@article{a, title={A}}" },
      { path: "b.bib", content: "@article{b, title={B}}" },
    ]);
    expect(bib).toBe("@article{a, title={A}}\n@article{b, title={B}}");
  });

  it("returns an empty string when the project has no .bib at all", () => {
    expect(collectPreflightBibContent([{ path: "main.tex", content: "x" }])).toBe("");
  });

  it("ignores .tex files and is case-insensitive about the extension", () => {
    const bib = collectPreflightBibContent([
      { path: "main.tex", content: "tex content" },
      { path: "REFS.BIB", content: "@article{a, title={A}}" },
    ]);
    expect(bib).toBe("@article{a, title={A}}");
  });
});

// --- final whole-branch review, FIX 3: which cross-file cause the panel should name -------------

describe("preflightCrossFileCauses", () => {
  it("names the missing-target cause when only unresolved_includes is populated", () => {
    expect(
      preflightCrossFileCauses({
        unresolved_includes: ["sections/gone.tex"],
        unexamined_files: [],
      }),
    ).toEqual(["unresolved_includes"]);
  });

  it("names the never-read cause when only unexamined_files is populated", () => {
    // A \subfile-wired project: the file is right there, so telling the author it "could not be
    // found" would be a false statement about their own project.
    expect(
      preflightCrossFileCauses({
        unresolved_includes: [],
        unexamined_files: ["sections/intro.tex"],
      }),
    ).toEqual(["unexamined_files"]);
  });

  it("names both causes when both apply, missing target first", () => {
    expect(
      preflightCrossFileCauses({
        unresolved_includes: ["sections/gone.tex"],
        unexamined_files: ["sections/intro.tex"],
      }),
    ).toEqual(["unresolved_includes", "unexamined_files"]);
  });

  it("never returns an empty list, so a suppressed row always carries a reason", () => {
    // runner.py cannot produce this report shape (it only suppresses these rules when one of the
    // two fields is non-empty), but an empty array here would render a rule name with no reason.
    expect(preflightCrossFileCauses({ unresolved_includes: [], unexamined_files: [] })).toEqual([
      "unresolved_includes",
    ]);
  });
});

describe("preflightCrossFileCauseFiles", () => {
  const report = {
    unresolved_includes: ["sections/gone.tex"],
    unexamined_files: ["sections/intro.tex"],
  };

  it("hands each cause its own file list, never the other one's", () => {
    expect(preflightCrossFileCauseFiles("unresolved_includes", report)).toEqual([
      "sections/gone.tex",
    ]);
    expect(preflightCrossFileCauseFiles("unexamined_files", report)).toEqual([
      "sections/intro.tex",
    ]);
  });
});
