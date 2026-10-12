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
import { isBibFile } from "@/lib/project-store";

/**
 * Every `.bib` in the project, concatenated, for `PreflightRequest.bib_content`.
 *
 * A single `.find()` here used to take whichever `.bib` happened to be first in array order and
 * silently discard the rest, so a paper with `refs.bib` + `extra.bib` and
 * `\bibliography{refs,extra}` reported `bib.cite_key_missing` at `critical` for every key living
 * in the dropped file — a false critical on a correct document, and on a layout the rest of the
 * product supports everywhere else (`overleaf-import.ts` and `latex-import.ts` import all `.bib`
 * files; `getCompilePayload` in project-store.ts ships all of them to the compiler). Which `.bib`
 * got picked was not visible to the author anywhere.
 *
 * Concatenation is safe for the one consumer that reads this: `parse_bib_entries`
 * (src/services/parser/latex.py) parses a BibTeX stream, and entries from two files are exactly a
 * longer stream. A duplicate key defined in two files stays visible to `bib.duplicate_entry`,
 * which is the correct report for that project.
 */
export function collectPreflightBibContent(files: PreflightFileInput[]): string {
  return files
    .filter((file) => isBibFile(file.path))
    .map((file) => file.content)
    .join("\n");
}

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

export type PreflightSuppressionReason =
  "unresolved_includes" | "unexamined_files" | "double_blind_conflict";

/** The two reasons a cross-file suppression can have — see `preflightCrossFileCauses`. */
export type PreflightCrossFileCause = Exclude<PreflightSuppressionReason, "double_blind_conflict">;

/**
 * Which FAMILY of suppression a rule in `report.suppressed` belongs to. `runner.py` suppresses
 * exactly two disjoint, fixed rule-id sets (`_CROSS_FILE_SUPPRESSED_RULES` when part of the
 * project went unread, `_DOUBLE_BLIND_SUPPRESSED_RULES` for the double-blind vs.
 * funding-statement conflict — spec §3.5), so the rule id alone decides the family.
 *
 * It does NOT decide the cross-file family's concrete cause: a missing \input target and a
 * payload file the include graph never reached suppress the identical rule ids, and only the
 * report's own two fields tell them apart. `preflightCrossFileCauses` does that half.
 */
export function preflightSuppressionReason(
  rule: string,
): "unresolved_includes" | "double_blind_conflict" {
  return rule.startsWith("crossref.") || rule.startsWith("bib.")
    ? "unresolved_includes"
    : "double_blind_conflict";
}

/**
 * The concrete cause(s) behind a cross-file suppression, in the order the panel should read them.
 * Both can apply at once (a project with a missing \input AND a \subfile-wired section), and
 * each gets its own sentence rather than one message hedging between them.
 *
 * Returns `["unresolved_includes"]` when both lists are empty. That report shape cannot occur —
 * `runner.py` only suppresses these rules when at least one of the two fields is non-empty — but
 * returning an empty array would leave the panel rendering a rule name followed by no reason at
 * all, which is worse than the generic sentence.
 */
export function preflightCrossFileCauses(report: {
  unresolved_includes: string[];
  unexamined_files: string[];
}): PreflightCrossFileCause[] {
  const causes: PreflightCrossFileCause[] = [];
  if (report.unresolved_includes.length) causes.push("unresolved_includes");
  if (report.unexamined_files.length) causes.push("unexamined_files");
  return causes.length ? causes : ["unresolved_includes"];
}

/** The file list the panel appends after a cross-file cause's sentence. */
export function preflightCrossFileCauseFiles(
  cause: PreflightCrossFileCause,
  report: { unresolved_includes: string[]; unexamined_files: string[] },
): string[] {
  return cause === "unresolved_includes" ? report.unresolved_includes : report.unexamined_files;
}
