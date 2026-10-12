import { resolveApiBase } from "./base-url";
import { mapApiHttpErrorFromResponse } from "./api-errors";
import { getAccessToken, logoutUser } from "@/lib/auth-store";
import type { UiLanguage } from "@/lib/locale-store";

const API_BASE = resolveApiBase();

// Mirrors `PREFLIGHT_RULE_IDS` in src/services/preflight/catalogue.py exactly — all 29 ids, same
// group order. tests/test_preflight/test_catalogue_parity.py asserts this union, read as text,
// equals that tuple; keep the two in lockstep by hand, there is no codegen here.
export type PreflightRuleId =
  // crossref.* (3.1)
  | "crossref.undefined_ref"
  | "crossref.float_without_label"
  | "crossref.unused_label"
  | "crossref.duplicate_label"
  // bib.* (3.2)
  | "bib.cite_key_missing"
  | "bib.duplicate_entry"
  | "bib.missing_required_field"
  | "bib.missing_doi"
  | "bib.uncited_entry"
  // statement.* (3.3)
  | "statement.data_availability_missing"
  | "statement.ethics_missing"
  | "statement.coi_missing"
  | "statement.funding_missing"
  | "statement.author_contributions_missing"
  // format.* (3.4)
  | "format.compressed_leading"
  | "format.margin_override"
  | "format.large_negative_vspace"
  | "format.font_size_override"
  // anon.* (3.5)
  | "anon.author_populated"
  | "anon.affiliation_populated"
  | "anon.email_present"
  | "anon.orcid_present"
  | "anon.thanks_present"
  | "anon.acknowledgements_present"
  | "anon.funding_identifiers"
  | "anon.self_reference"
  | "anon.repository_link"
  // length.* (3.6)
  | "length.over_limit"
  | "length.near_limit";

export type PreflightSeverity = "critical" | "warning" | "info";

export type PreflightFinding = {
  id: string;
  rule: PreflightRuleId;
  group: string;
  severity: PreflightSeverity;
  file: string;
  line: number | null;
  symbol: string;
  count: number;
  excerpt: string;
};

export type PreflightReport = {
  integrity_mode: string;
  findings: PreflightFinding[];
  counts: Record<string, number>;
  // A group that did not run: either not declared (anon without double-blind, length without a
  // word limit) or, on the no-content path, every group at once — see `no_content` below.
  skipped: string[];
  suppressed: string[];
  unresolved_includes: string[];
  // .tex files the request DID send that the \input/\include graph never reached, so nothing read
  // them (a \subfile / \import / \InputIfFileExists / \includeonly project, a conditional or
  // macro-wrapped include, or a stray unused file). Suppresses the same cross-file rules as
  // `unresolved_includes`, but must be worded differently — these files are not missing.
  unexamined_files: string[];
  // True when there was nothing to analyse at all (no files, or every resolved file is blank or
  // comment-only once masked). Distinct from `skipped`, which means "not declared" — a panel that
  // only checks `skipped.length` would render an empty draft as if every rule had passed.
  no_content: boolean;
};

export type PreflightProfileInput = {
  doubleBlind: boolean;
  wordLimit: number | null;
  requiredStatements: string[];
};

export type PreflightFileInput = { path: string; content: string };

export type RunPreflightOptions = {
  mainFile: string;
  files: PreflightFileInput[];
  bibContent?: string;
  profile: PreflightProfileInput;
  locale?: UiLanguage;
  signal?: AbortSignal;
};

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Submission Preflight — a deterministic, no-LLM static-analysis report over the LaTeX source.
 * Advisory only: nothing it returns edits the document or applies a fix.
 */
export async function runPreflight({
  mainFile,
  files,
  bibContent = "",
  profile,
  locale,
  signal,
}: RunPreflightOptions): Promise<PreflightReport> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/preflight/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        main_file: mainFile,
        files,
        bib_content: bibContent,
        profile: {
          double_blind: profile.doubleBlind,
          word_limit: profile.wordLimit,
          required_statements: profile.requiredStatements,
        },
      }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("NETWORK_ERROR", { cause: error });
  }
  if (res.status === 401) {
    logoutUser();
  }
  if (!res.ok) {
    throw new Error(await mapApiHttpErrorFromResponse(res, locale));
  }
  return (await res.json()) as PreflightReport;
}
