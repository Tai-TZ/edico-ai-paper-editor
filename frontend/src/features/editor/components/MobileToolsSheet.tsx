import { X } from "lucide-react";
import { useLocale } from "@/components/locale-context";
import { editorCopy } from "@/lib/editor-i18n";
import type { LLMProvider, LogicAuditReport, RevisionRecord } from "@/lib/api/academic";
import type {
  PreflightFinding,
  PreflightProfileInput,
  PreflightReport,
} from "@/lib/api/preflight-api";
import type { LogicAuditMode, LogicAuditScope } from "@/lib/logic-audit";
import type { StructureSuggestion } from "@/lib/structure-suggestions";
import type { ToolsTab } from "../types";
import { ToolsPanel } from "./ToolsPanel";

export function MobileToolsSheet({
  onClose,
  latex,
  projectId,
  autoCompile,
  onAutoCompileChange,
  revisions,
  citationResults,
  citationSummary,
  logicAuditReport,
  structureSuggestions,
  toolsTab,
  onToolsTabChange,
  onJumpToStructureSection,
  canJumpToStructureSection,
  onAskDicoStructure,
  onApplyStructureFix,
  onAskDicoCitation,
  onRunLogicAudit,
  logicAuditLoading,
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
  onClose: () => void;
  latex: string;
  projectId: string;
  autoCompile: boolean;
  onAutoCompileChange: (enabled: boolean) => void;
  revisions: RevisionRecord[];
  citationResults: Record<string, unknown>[];
  citationSummary: string;
  logicAuditReport: LogicAuditReport | null;
  structureSuggestions: StructureSuggestion[];
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
  const { locale } = useLocale();
  const t = editorCopy(locale);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background md:hidden">
      <header className="flex shrink-0 items-center justify-between border-b border-border/50 px-4 py-3 safe-area-pt">
        <h2 className="text-sm font-semibold">{t.mobile.tools}</h2>
        <button
          type="button"
          onClick={onClose}
          className="flex h-9 w-9 items-center justify-center rounded-full border border-border/50 text-muted-foreground transition hover:bg-secondary"
          aria-label={t.chatDock.closeChat}
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <ToolsPanel
          latex={latex}
          projectId={projectId}
          autoCompile={autoCompile}
          onAutoCompileChange={onAutoCompileChange}
          revisions={revisions}
          citationResults={citationResults}
          citationSummary={citationSummary}
          logicAuditReport={logicAuditReport}
          structureSuggestions={structureSuggestions}
          toolsTab={toolsTab}
          onToolsTabChange={onToolsTabChange}
          onJumpToStructureSection={onJumpToStructureSection}
          canJumpToStructureSection={canJumpToStructureSection}
          onAskDicoStructure={onAskDicoStructure}
          onApplyStructureFix={onApplyStructureFix}
          onAskDicoCitation={onAskDicoCitation}
          onRunLogicAudit={onRunLogicAudit}
          logicAuditLoading={logicAuditLoading}
          logicAuditReportStale={logicAuditReportStale}
          logicAuditProgressDetail={logicAuditProgressDetail}
          logicAuditSectionProgress={logicAuditSectionProgress}
          logicAuditEngineAvailable={logicAuditEngineAvailable}
          logicAuditScopeHint={logicAuditScopeHint}
          onCancelLogicAudit={onCancelLogicAudit}
          onJumpToLogicIssue={onJumpToLogicIssue}
          onAskDicoLogic={onAskDicoLogic}
          canJumpToLogicIssue={canJumpToLogicIssue}
          onCitationsUpdated={onCitationsUpdated}
          onClose={onClose}
          llmProvider={llmProvider}
          llmModel={llmModel}
          preflightReport={preflightReport}
          preflightLoading={preflightLoading}
          preflightError={preflightError}
          preflightProfile={preflightProfile}
          onPreflightProfileChange={onPreflightProfileChange}
          onRunPreflight={onRunPreflight}
          onJumpToPreflightFinding={onJumpToPreflightFinding}
          canJumpToPreflightFinding={canJumpToPreflightFinding}
        />
      </div>
    </div>
  );
}
