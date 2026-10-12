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

  it("says the word count is approximate", () => {
    expect(preflightCopy("en").approximate.trim()).not.toBe("");
    expect(preflightCopy("vi").approximate.trim()).not.toBe("");
  });
});
