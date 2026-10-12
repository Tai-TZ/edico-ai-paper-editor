import { useMemo } from "react";
import { Loader2, Play } from "lucide-react";

import { useLocale } from "@/components/locale-context";
import { Switch } from "@/components/ui/switch";
import type {
  PreflightFinding,
  PreflightProfileInput,
  PreflightReport,
  PreflightSeverity,
} from "@/lib/api/preflight-api";
import { assessManuscriptMaturity } from "@/lib/paper-score";
import { preflightCopy, type RequiredStatementId } from "@/lib/preflight-i18n";
import {
  PREFLIGHT_WORD_LIMIT_MAX,
  preflightSuppressionReason,
  sanitizeWordLimitInput,
} from "@/lib/preflight-panel";
import { cn } from "@/lib/utils";

type PreflightPanelProps = {
  /** Main file's source, used only to detect a fresh-from-template draft (design §7). */
  latex: string;
  report: PreflightReport | null;
  loading: boolean;
  error: string | null;
  profile: PreflightProfileInput;
  onProfileChange: (profile: PreflightProfileInput) => void;
  onRun: () => void;
  onJumpToFinding: (finding: PreflightFinding) => void;
  canJumpToFinding: (finding: PreflightFinding) => boolean;
};

const SEVERITY_ORDER: PreflightSeverity[] = ["critical", "warning", "info"];

const SEVERITY_CHIP: Record<PreflightSeverity, string> = {
  critical: "bg-destructive/15 text-destructive",
  warning: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
  info: "bg-sky-500/15 text-sky-800 dark:text-sky-300",
};

const REQUIRED_STATEMENT_IDS: RequiredStatementId[] = [
  "data_availability",
  "ethics",
  "coi",
  "funding",
  "author_contributions",
];

const SECONDARY_BTN = "text-[10px] font-medium text-primary hover:underline";

function groupLabelFor(t: ReturnType<typeof preflightCopy>, group: string): string {
  return (t.groupLabel as Record<string, string>)[group] ?? group;
}

function skippedReasonFor(t: ReturnType<typeof preflightCopy>, group: string): string {
  return (t.skippedReason as Record<string, string>)[group] ?? t.skippedGroup;
}

function ruleTitleFor(t: ReturnType<typeof preflightCopy>, rule: string): string {
  return (t.rules as Record<string, { title: string }>)[rule]?.title ?? rule;
}

export function PreflightPanel({
  latex,
  report,
  loading,
  error,
  profile,
  onProfileChange,
  onRun,
  onJumpToFinding,
  canJumpToFinding,
}: PreflightPanelProps) {
  const { locale } = useLocale();
  const t = preflightCopy(locale);

  // Fresh-from-template drafts are almost entirely `% TODO` placeholders — reuse the existing
  // maturity signal (paper-score.ts) rather than inventing a second heuristic for the same thing.
  const { isPlaceholderTemplate } = useMemo(() => assessManuscriptMaturity(latex), [latex]);

  const findingsBySeverity = useMemo(() => {
    const map: Record<PreflightSeverity, PreflightFinding[]> = {
      critical: [],
      warning: [],
      info: [],
    };
    for (const finding of report?.findings ?? []) {
      map[finding.severity]?.push(finding);
    }
    return map;
  }, [report]);

  const toggleStatement = (id: RequiredStatementId) => {
    const has = profile.requiredStatements.includes(id);
    onProfileChange({
      ...profile,
      requiredStatements: has
        ? profile.requiredStatements.filter((s) => s !== id)
        : [...profile.requiredStatements, id],
    });
  };

  const handleWordLimitChange = (raw: string) => {
    onProfileChange({ ...profile, wordLimit: sanitizeWordLimitInput(raw) });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-3 rounded-lg border border-border/70 bg-card/60 p-3">
        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          {t.profile.title}
        </h3>

        <div className="tools-setting-row">
          <div className="tools-setting-copy">
            <span className="tools-setting-label">{t.profile.doubleBlindLabel}</span>
            <span className="tools-setting-hint">{t.profile.doubleBlindHint}</span>
          </div>
          <Switch
            checked={profile.doubleBlind}
            onCheckedChange={(checked) => onProfileChange({ ...profile, doubleBlind: checked })}
            aria-label={t.profile.doubleBlindLabel}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <span className="text-[11px] font-medium text-foreground">
              {t.profile.wordLimitLabel}
            </span>
            <span className="text-[11px] text-muted-foreground">{t.profile.wordLimitHint}</span>
          </div>
          <input
            type="number"
            min={1}
            max={PREFLIGHT_WORD_LIMIT_MAX}
            inputMode="numeric"
            value={profile.wordLimit ?? ""}
            onChange={(e) => handleWordLimitChange(e.target.value)}
            className="w-24 rounded-md border border-border/60 bg-background px-2 py-1 text-xs"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] font-medium text-foreground">
            {t.profile.statementsLabel}
          </span>
          <span className="text-[11px] text-muted-foreground">{t.profile.statementsHint}</span>
          <div className="mt-1 flex flex-wrap gap-3">
            {REQUIRED_STATEMENT_IDS.map((id) => (
              <label key={id} className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={profile.requiredStatements.includes(id)}
                  onChange={() => toggleStatement(id)}
                  className="h-3.5 w-3.5 accent-[var(--primary)]"
                />
                {t.requiredStatementLabel[id]}
              </label>
            ))}
          </div>
        </div>
      </div>

      {isPlaceholderTemplate ? (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
          {t.placeholderTemplate}
        </p>
      ) : null}

      <button
        type="button"
        onClick={onRun}
        disabled={loading}
        className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {loading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Play className="h-3.5 w-3.5" />
        )}
        {loading ? t.running : t.run}
      </button>

      {error ? (
        <p
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      {!report && !loading && !error ? (
        <p className="text-xs text-muted-foreground">{t.beforeRun}</p>
      ) : null}

      {report ? (
        report.no_content ? (
          <p className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            {t.noContent}
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {report.findings.length === 0 ? (
              <p className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                {t.clean}
              </p>
            ) : null}

            {SEVERITY_ORDER.map((severity) => {
              const findings = findingsBySeverity[severity];
              if (!findings.length) return null;
              return (
                <section key={severity} className="space-y-2">
                  <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                    <span className={cn("rounded px-1.5 py-0.5", SEVERITY_CHIP[severity])}>
                      {t.severity[severity]}
                    </span>
                    {findings.length}
                  </h3>
                  <ul className="flex flex-col gap-2">
                    {findings.map((finding) => {
                      const ruleCopy = (t.rules as Record<string, { title: string; hint: string }>)[
                        finding.rule
                      ];
                      const jumpable = canJumpToFinding(finding);
                      const isLength = finding.rule.startsWith("length.");
                      return (
                        <li
                          key={finding.id}
                          className="rounded-lg border border-border/70 bg-card/80 p-3 text-xs"
                        >
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <span className="font-medium text-foreground">
                              {ruleCopy?.title ?? finding.rule}
                            </span>
                            {finding.count > 1 ? (
                              <span className="text-[10px] text-muted-foreground">
                                ×{finding.count}
                              </span>
                            ) : null}
                          </div>
                          {ruleCopy?.hint ? (
                            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                              {ruleCopy.hint}
                            </p>
                          ) : null}
                          {finding.symbol ? (
                            <code className="mt-1.5 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                              {finding.symbol}
                            </code>
                          ) : null}
                          {finding.excerpt ? (
                            <blockquote className="mt-1.5 whitespace-pre-wrap border-l-2 border-border pl-2 text-[11px] italic text-muted-foreground">
                              {finding.excerpt}
                            </blockquote>
                          ) : null}
                          {isLength ? (
                            <p className="mt-1.5 text-[10px] text-muted-foreground">
                              {t.approximate}
                            </p>
                          ) : null}
                          {jumpable ? (
                            <button
                              type="button"
                              className={cn(SECONDARY_BTN, "mt-2 block")}
                              onClick={() => onJumpToFinding(finding)}
                            >
                              {t.goToLine}
                            </button>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}

            {report.skipped.length ? (
              <section className="space-y-2">
                <h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                  {t.skippedGroupHeading}
                </h3>
                <ul className="flex flex-col gap-1.5">
                  {report.skipped.map((group) => (
                    <li
                      key={group}
                      className="rounded-md border border-dashed border-border/60 px-3 py-2 text-[11px] text-muted-foreground"
                    >
                      <span className="font-medium text-foreground">{groupLabelFor(t, group)}</span>{" "}
                      — {skippedReasonFor(t, group)}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {report.suppressed.length ? (
              <section className="space-y-2">
                <h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                  {t.suppressedRuleHeading}
                </h3>
                <ul className="flex flex-col gap-1.5">
                  {report.suppressed.map((rule) => {
                    const reason = preflightSuppressionReason(rule);
                    const includes = report.unresolved_includes;
                    return (
                      <li
                        key={rule}
                        className="rounded-md border border-dashed border-border/60 px-3 py-2 text-[11px] text-muted-foreground"
                      >
                        <span className="font-medium text-foreground">{ruleTitleFor(t, rule)}</span>{" "}
                        — {t.suppressedReason[reason]}
                        {reason === "unresolved_includes" && includes.length
                          ? ` (${includes.join(", ")})`
                          : ""}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ) : null}
          </div>
        )
      ) : null}
    </div>
  );
}
