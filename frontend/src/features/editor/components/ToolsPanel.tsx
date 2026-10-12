import { memo, useDeferredValue, useEffect, useMemo, useState } from "react";
import { HelpCircle, X } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { useLocale } from "@/components/locale-context";
import { CitationRelevancePanel } from "@/components/editor/citation-relevance-panel";
import { LogicAuditPanel } from "@/components/editor/logic-audit-panel";
import { PeerReviewPanel } from "@/components/editor/peer-review-panel";
import { StructureSuggestionsPanel } from "@/components/editor/structure-suggestions-panel";
import { Switch } from "@/components/ui/switch";
import { verifyCitations, type LogicAuditReport, type RevisionRecord } from "@/lib/api/academic";
import type { LLMProvider } from "@/lib/api/academic";
import type {
  PreflightFinding,
  PreflightProfileInput,
  PreflightReport,
} from "@/lib/api/preflight-api";
import { editorCopy, revisionActionLabel, translateCitationSummary } from "@/lib/editor-i18n";
import { peerReviewCopy } from "@/lib/peer-review-i18n";
import { preflightCopy } from "@/lib/preflight-i18n";
import { buildCitationFixPrompt } from "@/lib/citation-prompts";
import { formatTimeAgo, parseApiTimestamp } from "@/lib/project-store";
import type { LogicAuditMode, LogicAuditScope } from "@/lib/logic-audit";
import type { StructureSuggestion } from "@/lib/structure-suggestions";
import { computeProjectStats, countDiffStats } from "../lib/editor-project-stats";
import type { ToolsTab } from "../types";
import { PreflightPanel } from "./PreflightPanel";

export const ToolsPanel = memo(function ToolsPanel({
  latex,
  projectId,
  autoCompile,
  onAutoCompileChange,
  revisions,
  citationResults: citationResultsProp,
  citationSummary: citationSummaryProp,
  logicAuditReport: logicAuditReportProp,
  structureSuggestions = [],
  toolsTab,
  onToolsTabChange,
  onJumpToStructureSection,
  canJumpToStructureSection,
  onAskDicoStructure,
  onApplyStructureFix,
  onAskDicoCitation,
  onRunLogicAudit,
  logicAuditLoading = false,
  logicAuditReportStale = false,
  logicAuditProgressDetail = null,
  logicAuditSectionProgress = null,
  logicAuditEngineAvailable = true,
  logicAuditScopeHint = null,
  onCancelLogicAudit,
  onJumpToLogicIssue,
  onAskDicoLogic,
  canJumpToLogicIssue,
  onCitationsUpdated,
  onClose,
  llmProvider,
  llmModel,
  preflightReport,
  preflightLoading = false,
  preflightError = null,
  preflightProfile,
  onPreflightProfileChange,
  onRunPreflight,
  onJumpToPreflightFinding,
  canJumpToPreflightFinding,
}: {
  latex: string;
  projectId: string;
  autoCompile: boolean;
  onAutoCompileChange: (enabled: boolean) => void;
  revisions: RevisionRecord[];
  citationResults: Record<string, unknown>[];
  citationSummary: string;
  logicAuditReport: LogicAuditReport | null;
  structureSuggestions?: StructureSuggestion[];
  toolsTab: ToolsTab;
  onToolsTabChange: (tab: ToolsTab) => void;
  onJumpToStructureSection: (sectionName: string) => void;
  canJumpToStructureSection: (sectionName: string) => boolean;
  onAskDicoStructure: (prefill: string) => void;
  onApplyStructureFix?: (suggestion: StructureSuggestion) => void;
  onAskDicoCitation: (prefill: string, citeKey?: string) => void;
  onRunLogicAudit: (mode: LogicAuditMode, scope: LogicAuditScope, sections: string[]) => void;
  logicAuditLoading?: boolean;
  logicAuditReportStale?: boolean;
  logicAuditProgressDetail?: string | null;
  logicAuditSectionProgress?: { completed: number; total: number } | null;
  logicAuditEngineAvailable?: boolean;
  logicAuditScopeHint?: LogicAuditScope | null;
  onCancelLogicAudit?: () => void;
  onJumpToLogicIssue?: (sectionName: string, excerpt?: string) => void;
  onAskDicoLogic?: (prefill: string, sectionName: string, excerpt?: string) => void;
  canJumpToLogicIssue?: (sectionName: string, excerpt?: string) => boolean;
  onCitationsUpdated: (results: Record<string, unknown>[], summary: string) => void;
  onClose: () => void;
  llmProvider?: LLMProvider;
  llmModel?: string;
  preflightReport: PreflightReport | null;
  preflightLoading?: boolean;
  preflightError?: string | null;
  preflightProfile: PreflightProfileInput;
  onPreflightProfileChange: (profile: PreflightProfileInput) => void;
  onRunPreflight: () => void;
  onJumpToPreflightFinding: (finding: PreflightFinding) => void;
  canJumpToPreflightFinding: (finding: PreflightFinding) => boolean;
}) {
  const tab = toolsTab;
  const setTab = onToolsTabChange;
  const { locale } = useLocale();
  const t = editorCopy(locale);
  const [citationResults, setCitationResults] = useState(citationResultsProp);
  const [citationSummary, setCitationSummary] = useState(citationSummaryProp);
  const [citationLoading, setCitationLoading] = useState(false);

  useEffect(() => {
    setCitationResults(citationResultsProp);
    setCitationSummary(citationSummaryProp);
  }, [citationResultsProp, citationSummaryProp]);

  useEffect(() => {
    if (logicAuditReportProp?.sections?.length) {
      setTab("logic");
    }
  }, [logicAuditReportProp, setTab]);

  useEffect(() => {
    if (structureSuggestions.length) {
      setTab("structure");
    }
  }, [structureSuggestions, setTab]);

  const sortedRevisions = useMemo(
    () =>
      [...revisions].sort(
        (a, b) => parseApiTimestamp(b.created_at) - parseApiTimestamp(a.created_at),
      ),
    [revisions],
  );

  // Word/figure counts scan the whole document; compute them at background priority (deferred)
  // and only when the source changed, not on every panel re-render or keystroke.
  const deferredLatex = useDeferredValue(latex);
  const stats = useMemo(() => computeProjectStats(deferredLatex), [deferredLatex]);

  const statCards: { label: string; value: number }[] = [
    { label: t.tools.stats.words, value: stats.words },
    { label: t.tools.stats.wordsInText, value: stats.wordsInText },
    { label: t.tools.stats.wordsInHeaders, value: stats.wordsInHeaders },
    { label: t.tools.stats.wordsOutsideText, value: stats.wordsOutsideText },
    { label: t.tools.stats.headers, value: stats.headers },
    { label: t.tools.stats.figures, value: stats.figures },
    { label: t.tools.stats.mathInlines, value: stats.mathInlines },
    { label: t.tools.stats.mathDisplayed, value: stats.mathDisplayed },
  ];

  const handleVerifyCitations = async () => {
    if (!projectId) return;
    setCitationLoading(true);
    try {
      const result = await verifyCitations(projectId);
      setCitationResults(result.results);
      setCitationSummary(result.summary);
      onCitationsUpdated(result.results, result.summary);
    } catch {
      setCitationSummary(t.tools.citationVerifyError);
    } finally {
      setCitationLoading(false);
    }
  };

  return (
    <section className="tools-panel flex h-full min-h-0 flex-col bg-secondary/20">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border/60 bg-card/80 px-3 backdrop-blur-sm min-w-0">
        <nav className="tools-tab-nav flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {(
            [
              { id: "info" as const, label: t.tools.projectInfo },
              { id: "structure" as const, label: t.tools.structure },
              { id: "logic" as const, label: t.tools.logicAudit },
              { id: "citations" as const, label: t.tools.citations },
              { id: "peerReview" as const, label: peerReviewCopy(locale).tab },
              { id: "preflight" as const, label: preflightCopy(locale).tab },
              { id: "versions" as const, label: t.tools.versions },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`tools-tab-btn ${tab === item.id ? "is-active" : ""}`}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <button
          onClick={onClose}
          className="flex shrink-0 items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground transition hover:bg-primary/90"
        >
          <X className="h-3 w-3" />
          {t.tools.close}
        </button>
      </div>

      <div className="soft-scrollbar flex-1 overflow-y-auto p-4 md:p-5">
        {tab === "info" ? (
          <div className="tools-section">
            <h2 className="tools-section-title">{t.tools.settings}</h2>
            <div className="tools-setting-row">
              <div className="tools-setting-copy">
                <span className="tools-setting-label">{t.tools.autoCompile}</span>
                <span className="tools-setting-hint">{t.tools.autoCompileHint}</span>
              </div>
              <Switch
                id="tools-auto-compile"
                checked={autoCompile}
                onCheckedChange={onAutoCompileChange}
                aria-label={t.tools.autoCompile}
              />
            </div>

            <div className="tools-setting-row">
              <div className="tools-setting-copy">
                <span className="tools-setting-label">{t.tools.researcherProfile}</span>
                <span className="tools-setting-hint">{t.tools.researcherProfileHint}</span>
              </div>
              <Link
                to="/profile"
                className="rounded-md border border-border/60 px-2.5 py-1 text-[11px] font-medium transition hover:bg-secondary"
              >
                {t.tools.open}
              </Link>
            </div>

            <h2 className="tools-section-title mt-6">{t.tools.summary}</h2>
            <div className="tools-stat-grid">
              {statCards.map((card) => (
                <div key={card.label} className="tools-stat-card">
                  <span className="tools-stat-label">{card.label}</span>
                  <span className="tools-stat-value">{card.value}</span>
                </div>
              ))}
            </div>
          </div>
        ) : tab === "structure" ? (
          <div className="tools-section">
            <h2 className="tools-section-title">{t.tools.structure}</h2>
            <StructureSuggestionsPanel
              suggestions={structureSuggestions}
              onJumpToSection={onJumpToStructureSection}
              onAskDico={onAskDicoStructure}
              onApplyFix={onApplyStructureFix}
              canJump={canJumpToStructureSection}
            />
          </div>
        ) : tab === "logic" ? (
          <div className="tools-section">
            <h2 className="tools-section-title">{t.tools.logicAudit}</h2>
            <LogicAuditPanel
              latex={latex}
              report={logicAuditReportProp}
              loading={logicAuditLoading}
              reportStale={logicAuditReportStale}
              progressDetail={logicAuditProgressDetail}
              sectionProgress={logicAuditSectionProgress}
              engineAvailable={logicAuditEngineAvailable}
              scopeHint={logicAuditScopeHint}
              onRun={onRunLogicAudit}
              onCancel={onCancelLogicAudit}
              onJumpToIssue={onJumpToLogicIssue}
              onAskDico={onAskDicoLogic}
              canJumpToIssue={canJumpToLogicIssue}
            />
          </div>
        ) : tab === "peerReview" ? (
          <div className="tools-section">
            <h2 className="tools-section-title">{peerReviewCopy(locale).title}</h2>
            <PeerReviewPanel
              key={projectId}
              projectId={projectId}
              latex={latex}
              llmProvider={llmProvider}
              llmModel={llmModel}
            />
          </div>
        ) : tab === "citations" ? (
          <div className="tools-section">
            <div className="flex items-center justify-between">
              <h2 className="tools-section-title mb-0">{t.tools.citationVerification}</h2>
              <button
                type="button"
                onClick={handleVerifyCitations}
                disabled={citationLoading}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {citationLoading ? t.tools.verifying : t.tools.verifyCitations}
              </button>
            </div>
            {citationSummary && (
              <p className="mt-3 text-sm text-muted-foreground">
                {translateCitationSummary(locale, citationSummary)}
              </p>
            )}
            {citationResults.some((r) => r.status !== "verified") ? (
              <button
                type="button"
                className="mt-3 inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground transition hover:bg-primary/90"
                onClick={() => {
                  const first = citationResults.find((r) => r.status !== "verified");
                  onAskDicoCitation(
                    buildCitationFixPrompt(),
                    first?.key ? String(first.key) : undefined,
                  );
                }}
              >
                {t.tools.citationFixAll}
              </button>
            ) : null}
            <CitationRelevancePanel
              key={projectId}
              projectId={projectId}
              latex={latex}
              citationResults={citationResults}
            />
            <ul className="mt-4 space-y-2">
              {citationResults.map((r, i) => (
                <li
                  key={i}
                  className="rounded-lg border border-border/50 bg-card px-3 py-2 text-xs"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <span
                      className={
                        r.status === "verified"
                          ? "text-emerald-600 font-medium"
                          : "text-destructive font-medium"
                      }
                    >
                      {String(r.status)} — {String(r.key ?? "")}
                    </span>
                    {r.status !== "verified" ? (
                      <button
                        type="button"
                        className="shrink-0 rounded border border-border px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition hover:bg-secondary"
                        onClick={() =>
                          onAskDicoCitation(
                            buildCitationFixPrompt(String(r.key ?? "")),
                            String(r.key ?? ""),
                          )
                        }
                      >
                        {t.tools.citationAskDico}
                      </button>
                    ) : null}
                  </div>
                  <p className="mt-1 text-muted-foreground">
                    {String(r.title || t.tools.noTitleInBib)}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        ) : tab === "preflight" ? (
          <div className="tools-section">
            <h2 className="tools-section-title">{preflightCopy(locale).tab}</h2>
            <PreflightPanel
              latex={latex}
              report={preflightReport}
              loading={preflightLoading}
              error={preflightError}
              profile={preflightProfile}
              onProfileChange={onPreflightProfileChange}
              onRun={onRunPreflight}
              onJumpToFinding={onJumpToPreflightFinding}
              canJumpToFinding={canJumpToPreflightFinding}
            />
          </div>
        ) : (
          <div className="tools-section">
            <div className="flex items-center gap-2">
              <h2 className="tools-section-title mb-0">{t.tools.aiRevisionHistory}</h2>
              <button
                className="flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                aria-label={t.tools.versionsHelp}
              >
                <HelpCircle className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t.tools.revisionsHint}</p>

            {sortedRevisions.length === 0 ? (
              <p className="mt-4 text-xs text-muted-foreground">{t.tools.noRevisions}</p>
            ) : (
              <div className="mt-4 space-y-3">
                {sortedRevisions.map((rev, index) => {
                  const { additions, deletions } = countDiffStats(rev.original, rev.suggestion);
                  return (
                    <div
                      key={rev.id}
                      className="tools-version-entry flex-col items-stretch gap-2 !py-3"
                    >
                      <div className="flex items-center gap-2">
                        <span className="tools-version-pill">
                          #{sortedRevisions.length - index}
                        </span>
                        <span
                          className={`tools-version-pill ${
                            rev.action === "accepted"
                              ? "text-emerald-700"
                              : rev.action === "rejected"
                                ? "text-destructive"
                                : ""
                          }`}
                        >
                          {revisionActionLabel(locale, rev.action)}
                        </span>
                        {rev.section && (
                          <span className="text-xs text-muted-foreground">{rev.section}</span>
                        )}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {formatTimeAgo(rev.created_at, locale)}
                        </span>
                      </div>
                      <p className="line-clamp-2 text-xs text-muted-foreground">{rev.original}</p>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="tools-diff">
                          <span className="text-emerald-600">+{additions}</span>
                          <span className="text-[color:var(--destructive)]">-{deletions}</span>
                        </span>
                        <span className="text-muted-foreground">{t.tools.charsVsOriginal}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
});
