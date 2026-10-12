import { describe, expect, it } from "vitest";
import { preflightCopy } from "./preflight-i18n";

/**
 * Recursively collects every string leaf in a nested copy object, labelled with its dotted path
 * (e.g. "profile.doubleBlindHint", "rules.crossref.undefined_ref.title") for useful failure
 * messages. `preflightCopy`'s shape is a tree of plain objects and strings only — no arrays, no
 * other primitives — so this is exhaustive without needing per-field special-casing.
 */
function collectLeafStrings(value: unknown, path: string[] = []): Array<[string, string]> {
  if (typeof value === "string") return [[path.join("."), value]];
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
      collectLeafStrings(child, [...path, key]),
    );
  }
  return [];
}

describe("preflightCopy", () => {
  it("gives every leaf string in PreflightCopy a non-empty value in both locales", () => {
    // Previously this only walked `copy.rules` — `profile.*`, `groupLabel.*`, `skippedReason.*`,
    // and top-level strings like `clean` (a stated spec requirement) had zero coverage: dropping
    // a key, or emptying a string, anywhere outside `rules` stayed green. Walking the whole tree
    // closes that gap for every current and future field at once.
    for (const locale of ["en", "vi"] as const) {
      const copy = preflightCopy(locale);
      for (const [path, text] of collectLeafStrings(copy)) {
        expect(text.trim(), `${locale}/${path}`).not.toBe("");
      }
    }
  });

  it("does not leave Vietnamese copy identical to English", () => {
    const en = preflightCopy("en");
    const vi = preflightCopy("vi");
    const same = Object.keys(en.rules).filter(
      (r) =>
        en.rules[r as keyof typeof en.rules].title === vi.rules[r as keyof typeof vi.rules].title,
    );
    expect(same).toEqual([]);
  });

  it("says the word count is approximate and varies by venue", () => {
    // Substring checks, not a whole-sentence match, so ordinary rewording stays green — but
    // gutting either idea (it's an estimate; venues count differently) must fail.
    const en = preflightCopy("en").approximate;
    expect(en).toMatch(/\bestimate\b/i);
    expect(en).toMatch(/venue/i);
    expect(en).toMatch(/differently/i);

    const vi = preflightCopy("vi").approximate;
    expect(vi).toMatch(/ước tính/i);
    expect(vi).toMatch(/khác nhau/i);
  });

  it("says a clean result is not a guarantee of acceptance, in both locales", () => {
    // Substring checks, same discipline as `approximate` above: ordinary rewording stays green,
    // but gutting the "mechanical check, not a guarantee" idea — the spec requirement this string
    // exists to satisfy — must fail.
    const en = preflightCopy("en").clean;
    expect(en).toMatch(/no issues/i);
    expect(en).toMatch(/not a guarantee/i);
    expect(en).toMatch(/call for papers/i);

    const vi = preflightCopy("vi").clean;
    expect(vi).toMatch(/không phát hiện/i);
    expect(vi).toMatch(/chấp nhận/i);
    expect(vi).toMatch(/mời bài/i);
  });

  it("warns about a fresh-from-template draft in both locales (design §7)", () => {
    // A paper just created from a template is almost all `% TODO` placeholders with no real
    // content — the panel must say so instead of silently listing findings against a document
    // the author hasn't written yet.
    const en = preflightCopy("en").placeholderTemplate;
    expect(en.trim()).not.toBe("");
    expect(en).toMatch(/template/i);

    const vi = preflightCopy("vi").placeholderTemplate;
    expect(vi.trim()).not.toBe("");
    expect(vi).toMatch(/mẫu/i);

    expect(en).not.toBe(vi);
  });
});
