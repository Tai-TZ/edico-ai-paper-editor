import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_PREFLIGHT_PROFILE,
  canJumpToPreflightFinding,
  loadPreflightProfile,
  preflightLineCount,
  preflightSuppressionReason,
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
});

describe("preflightSuppressionReason", () => {
  it("attributes crossref and bib rules to the unresolved-\\input conflict", () => {
    expect(preflightSuppressionReason("crossref.undefined_ref")).toBe("unresolved_includes");
    expect(preflightSuppressionReason("bib.uncited_entry")).toBe("unresolved_includes");
  });

  it("attributes statement rules to the double-blind conflict", () => {
    expect(preflightSuppressionReason("statement.funding_missing")).toBe("double_blind_conflict");
    expect(preflightSuppressionReason("statement.author_contributions_missing")).toBe(
      "double_blind_conflict",
    );
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
    expect(loadPreflightProfile(paperId)).toEqual(DEFAULT_PREFLIGHT_PROFILE);
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
