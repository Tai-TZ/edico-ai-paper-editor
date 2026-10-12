/**
 * Pure helpers behind the Submission Preflight panel — split out from the hook/component so the
 * logic that CAN be unit tested (no DOM, no React) actually is, following `logic-audit.ts`'s
 * precedent of plain functions over an entry point that only renders.
 */
import type {
  PreflightFileInput,
  PreflightFinding,
  PreflightProfileInput,
} from "@/lib/api/preflight-api";

export const DEFAULT_PREFLIGHT_PROFILE: PreflightProfileInput = {
  doubleBlind: false,
  wordLimit: null,
  // Mirrors `PreflightProfile`'s default in src/models/preflight_schemas.py: author_contributions
  // starts off because many venues don't require it (spec §3.3).
  requiredStatements: ["data_availability", "ethics", "coi", "funding"],
};

function preflightProfileStorageKey(paperId: string): string {
  return `edico-preflight-profile:${paperId}`;
}

/**
 * Per-paper declared profile, kept in localStorage (no DB column in v1 — design §5). Returns the
 * default on a missing key, an empty `paperId` (unsaved project), or anything malformed, so a
 * corrupt value never throws into the render path.
 */
export function loadPreflightProfile(paperId: string): PreflightProfileInput {
  if (!paperId || typeof localStorage === "undefined") return DEFAULT_PREFLIGHT_PROFILE;
  try {
    const raw = localStorage.getItem(preflightProfileStorageKey(paperId));
    if (!raw) return DEFAULT_PREFLIGHT_PROFILE;
    const parsed = JSON.parse(raw) as Partial<PreflightProfileInput> | null;
    if (!parsed || typeof parsed !== "object") return DEFAULT_PREFLIGHT_PROFILE;
    return {
      doubleBlind: Boolean(parsed.doubleBlind),
      wordLimit:
        typeof parsed.wordLimit === "number" &&
        Number.isFinite(parsed.wordLimit) &&
        parsed.wordLimit > 0
          ? Math.floor(parsed.wordLimit)
          : null,
      requiredStatements: Array.isArray(parsed.requiredStatements)
        ? parsed.requiredStatements.filter((s): s is string => typeof s === "string")
        : DEFAULT_PREFLIGHT_PROFILE.requiredStatements,
    };
  } catch {
    return DEFAULT_PREFLIGHT_PROFILE;
  }
}

export function savePreflightProfile(paperId: string, profile: PreflightProfileInput): void {
  if (!paperId || typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(preflightProfileStorageKey(paperId), JSON.stringify(profile));
  } catch {
    // Quota exceeded or private-mode storage access denied — persistence is a nicety, never a
    // requirement for running a check, so swallow and keep the in-memory profile working.
  }
}

/** 1-based line count — same `split(/\r?\n/)` convention as `latex-outline.ts`'s `lineAtOffset`; never 0. */
export function preflightLineCount(content: string): number {
  return content.split(/\r?\n/).length;
}

/**
 * `scrollToLineInternal` (components/latex-code-editor.tsx) only guards `line < 1`; it does not
 * clamp a line past end-of-file, so trusting the backend's `line` unconditionally would scroll to
 * the bottom of the file and highlight nothing. Re-validate against the finding's own file before
 * a jump button is allowed to be clickable at all.
 */
export function canJumpToPreflightFinding(
  finding: Pick<PreflightFinding, "file" | "line">,
  files: PreflightFileInput[],
): boolean {
  if (finding.line == null || finding.line < 1) return false;
  const file = files.find((f) => f.path === finding.file);
  if (!file) return false;
  return finding.line <= preflightLineCount(file.content);
}

/**
 * Upper bound for the live word-limit input, mirroring `Field(ge=1, le=100_000)` on
 * `PreflightProfile.word_limit` (src/models/preflight_schemas.py:29). Without this, typing e.g.
 * 200000 reaches the backend unclamped and comes back as a generic 422 error banner instead of
 * being caught here as a field-level hint.
 */
export const PREFLIGHT_WORD_LIMIT_MAX = 100_000;

/**
 * Sanitises the live word-limit input field: an empty (or whitespace-only) string clears the
 * limit, anything else is floored and clamped to `[1, PREFLIGHT_WORD_LIMIT_MAX]` so the value
 * handed to `onProfileChange` can never violate the backend's bounds. Non-finite input (e.g. a
 * bare "-" while typing, or "abc") also falls back to `null` rather than throwing or persisting
 * `NaN`.
 */
export function sanitizeWordLimitInput(raw: string): number | null {
  if (raw.trim() === "") return null;
  const parsed = Math.floor(Number(raw));
  if (!Number.isFinite(parsed)) return null;
  return Math.min(PREFLIGHT_WORD_LIMIT_MAX, Math.max(1, parsed));
}

export type PreflightSuppressionReason = "unresolved_includes" | "double_blind_conflict";

/**
 * Why a rule in `report.suppressed` was turned off. `runner.py` suppresses exactly two disjoint,
 * fixed rule-id sets (`_CROSS_FILE_SUPPRESSED_RULES` for a missing \input target,
 * `_DOUBLE_BLIND_SUPPRESSED_RULES` for the double-blind vs. funding-statement conflict — spec
 * §3.5), so the rule id alone determines which reason applies; no extra report field needed.
 */
export function preflightSuppressionReason(rule: string): PreflightSuppressionReason {
  return rule.startsWith("crossref.") || rule.startsWith("bib.")
    ? "unresolved_includes"
    : "double_blind_conflict";
}
