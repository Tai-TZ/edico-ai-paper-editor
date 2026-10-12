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
