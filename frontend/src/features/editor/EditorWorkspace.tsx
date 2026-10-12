import { Link, useBlocker, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState, type InputHTMLAttributes } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EditorSelectionToolbar } from "@/components/editor-selection-toolbar";
import { EditorOnboardingDialog } from "@/components/editor/editor-onboarding-dialog";
import { ProjectAssetPreview } from "@/components/editor/project-asset-preview";
import { EditorEntrySplash } from "@/components/editor-entry-splash";
import { EditorDesktopPanels } from "@/components/editor-desktop-panels";
import { PaperScoreDownloadDialog } from "@/components/editor/paper-score-download-dialog";
import { ShareLinkDialog } from "@/components/editor/share-link-dialog";
import { PanelErrorBoundary } from "@/components/panel-error-boundary";
import { PdfPreviewPanel } from "@/components/pdf-preview-panel";
import { SuggestionPanel } from "@/components/suggestion-panel";
import { useLocale } from "@/components/locale-context";
import { updatePaper } from "@/lib/api/papers-api";
import { commonCopy } from "@/lib/common-i18n";
import { editorCopy } from "@/lib/editor-i18n";
import { editorShellCopy } from "@/lib/editor-shell-i18n";
import { formatLogicAuditProgress } from "@/lib/logic-audit";
import type { EditorSelectionContext, SelectionAnchor } from "@/lib/editor-selection-anchor";
import { isImageAssetFile, type LatexCompiler } from "@/lib/project-store";
import { useLatestRef } from "@/lib/use-latest-ref";
import type { LatexCodeEditorHandle } from "@/components/latex-code-editor";
import { Route } from "@/routes/editor";
import { persistChatThreads } from "./lib/editor-thread-storage";
import { toInlineSuggestion } from "./lib/editor-inline-suggestion";
import { EDITOR_SIDEBAR_STORAGE_KEY, readSidebarExpanded } from "./lib/editor-sidebar-prefs";
import { hasSeenEditorOnboarding } from "./lib/editor-onboarding-prefs";
import { EdicoMasthead } from "./components/EdicoMasthead";
import { CenterPanel } from "./components/CenterPanel";
import { LatexEditor } from "./components/LatexEditor";
import { LeftSidebar } from "./components/LeftSidebar";
import { MobileBottomBar } from "./components/MobileBottomBar";
import { MobileChatSheet } from "./components/MobileChatSheet";
import { MobileFilesPanel } from "./components/MobileFilesPanel";
import { MobileHeader } from "./components/MobileHeader";
import { MobileTabBar } from "./components/MobileTabBar";
import { MobileToolsSheet } from "./components/MobileToolsSheet";
import { PendingEditsPanel } from "./components/PendingEditsPanel";
import { StatusBar } from "./components/StatusBar";
import { ToolsPanel } from "./components/ToolsPanel";
import type { MobileTab } from "./types";
import { useEditorChat } from "./state/useEditorChat";
import { useEditorPreflight } from "./state/useEditorPreflight";
import { useEditorProject, type EditorProjectBootPayload } from "./state/useEditorProject";
import { useEditorProviders } from "./state/useEditorProviders";
import { useEditorTools, type EditorToolsChatBridge } from "./state/useEditorTools";
import { useLatexWorkspace } from "./state/useLatexWorkspace";

/**
 * Ctrl+Z / Ctrl+Y typed into another field (chat, rename, search…) belong to that field;
 * only the LaTeX editor's own textarea maps them to project undo/redo.
 */
function isOtherEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.closest(".latex-input")) return false;
  return target.isContentEditable || target.matches("input, textarea, select");
}

type LeaveLocation = { pathname: string; search: unknown };

function projectIdOf(search: unknown): unknown {
  return (search as { projectId?: unknown } | null)?.projectId;
}

export function EditorWorkspace() {
  const navigate = useNavigate();
  const { locale } = useLocale();
  const shell = useMemo(() => commonCopy(locale).shell, [locale]);
  const t = useMemo(() => editorCopy(locale), [locale]);
  const shellCopy = useMemo(() => editorShellCopy(locale), [locale]);
  const { projectId } = Route.useSearch();

  const [sidebarTab, setSidebarTab] = useState<"files" | "chats">("files");
  const [sidebarExpanded, setSidebarExpanded] = useState(readSidebarExpanded);
  const [mobileTab, setMobileTab] = useState<MobileTab>("editor");
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const [mobileToolsOpen, setMobileToolsOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const onboardingScheduledRef = useRef(false);
  const [selection, setSelection] = useState("");
  const [selectionPick, setSelectionPick] = useState<{
    context: EditorSelectionContext;
    anchor: SelectionAnchor;
  } | null>(null);
  const [statusLineCount, setStatusLineCount] = useState(1);
  const [bootAudit, setBootAudit] = useState<EditorProjectBootPayload | null>(null);

  const latexEditorRef = useRef<LatexCodeEditorHandle>(null);
  const persistActiveThreadNowRef = useRef<() => void>(() => {});
  const resetCompileCacheRef = useRef<() => void>(() => {});
  const chatHydratedForProjectRef = useRef<string | null>(null);

  const resetCompileOnImport = useCallback(() => {
    resetCompileCacheRef.current();
  }, []);

  const project = useEditorProject({
    projectId,
    navigate,
    locale,
    onBootReady: setBootAudit,
    onImportComplete: resetCompileOnImport,
  });

  const providersState = useEditorProviders();

  const latexWs = useLatexWorkspace({
    projectId,
    projectName: project.projectName,
    latex: project.latex,
    projectFiles: project.projectFiles,
    activeFile: project.activeFile,
    mainFile: project.mainFile,
    compiler: project.compiler,
    assets: project.assets,
    persistActiveFile: project.persistActiveFile,
    persistableFile: project.persistableFile,
    switchActiveFile: project.switchActiveFile,
    latexEditorRef,
    synctexHighlightMs: project.synctexHighlightMs,
    setMobileTab,
    compileAfterEditOk: t.chatStream.compileAfterEditOk,
    compileAfterEditFail: t.chatStream.compileAfterEditFail,
  });

  resetCompileCacheRef.current = latexWs.resetCompileCache;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setStatusLineCount(project.latex.split("\n").length);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [project.latex]);

  const chatBridgeRef = useRef<
    Pick<EditorToolsChatBridge, "queueChatFollowUp" | "runAgentEdit" | "openChatPanel">
  >({
    queueChatFollowUp: () => {},
    runAgentEdit: () => {},
    openChatPanel: () => {},
  });

  const tools = useEditorTools({
    projectId,
    locale,
    mainLatexSource: project.mainLatexSource,
    mainFile: project.mainFile,
    activeFile: project.activeFile,
    integrityStrictness: project.integrityStrictness,
    llmProvider: providersState.llmProvider,
    llmModel: providersState.llmModel,
    providers: providersState.providers,
    switchActiveFile: project.switchActiveFile,
    jumpToOutlineLine: latexWs.jumpToOutlineLine,
    exportOpen,
    chatBridgeRef,
    setMobileToolsOpen,
    panelAuditFingerprintFromBoot: bootAudit?.mainLatexFingerprint ?? null,
    gateAuditFingerprintFromBoot: bootAudit?.gateAuditFingerprint ?? null,
    bootLogicAuditReport: bootAudit?.logicAuditReport ?? null,
    bootGateAuditReport: bootAudit?.gateAuditReport ?? null,
  });

  const preflight = useEditorPreflight({
    projectId,
    locale,
    mainFile: project.mainFile,
    activeFile: project.activeFile,
    projectFiles: project.projectFiles,
    switchActiveFile: project.switchActiveFile,
    jumpToOutlineLine: latexWs.jumpToOutlineLine,
  });

  const chat = useEditorChat({
    projectId,
    projectName: project.projectName,
    locale,
    latex: project.latex,
    mainFile: project.mainFile,
    activeFile: project.activeFile,
    mainLatexSource: project.mainLatexSource,
    projectFiles: project.projectFiles,
    selection,
    setSelection,
    integrityStrictness: project.integrityStrictness,
    llmProvider: providersState.llmProvider,
    llmModel: providersState.llmModel,
    providers: providersState.providers,
    setLlmProvider: providersState.setLlmProvider,
    setLlmModel: providersState.setLlmModel,
    autoCompile: project.autoCompile,
    undo: project.undo,
    redo: project.redo,
    canUndo: project.canUndo,
    canRedo: project.canRedo,
    recordNow: project.recordNow,
    setProjectFiles: project.setProjectFiles,
    persistActiveFile: project.persistActiveFile,
    refreshRevisions: tools.refreshRevisions,
    scheduleCompile: latexWs.scheduleCompile,
    compileNow: latexWs.handleCompile,
    onCompileAfterEdit: latexWs.markCompileAfterEdit,
    onAfterEditAccepted: project.saveProjectAfterEdit,
    setMobileChatOpen,
    scoreAuditLoading: tools.scoreAuditLoading,
    sideEffects: tools.chatSideEffects,
  });

  const {
    chatThreads,
    activeChatId,
    chatOpen,
    auditInProgress,
    auditSectionProgress,
    logicAuditScopeHint,
    chatStreamProgress,
    setChatSelectionContext,
    chatComposerMode,
    setChatComposerMode,
    pendingEdits,
    pendingSuggestion,
    activeEditId,
    setActiveEditId,
    resolveFileContent,
    handleNewChat,
    handleSwitchChat,
    handleRenameChat,
    handleDeleteChat,
    handleStopChat,
    openChatPanel,
    queueChatFollowUp,
    handleAcceptEdit,
    handleRejectEdit,
    handleAcceptAllEdits,
    handleRejectAllEdits,
    handleAcceptSuggestion,
    handleRejectSuggestion,
    runLogicAuditFromPanel,
    runAgentEdit,
    hydrateChatFromProject,
    persistActiveThreadNow,
    chatProps,
    setChatInput,
  } = chat;

  persistActiveThreadNowRef.current = persistActiveThreadNow;

  const inlineSuggestion = useMemo(
    () => toInlineSuggestion(pendingEdits, activeEditId, pendingSuggestion),
    [pendingEdits, activeEditId, pendingSuggestion],
  );

  chatBridgeRef.current = {
    queueChatFollowUp,
    runAgentEdit,
    openChatPanel,
  };

  const {
    persistProjectFiles,
    autoCompile: projectAutoCompile,
    latex: projectLatex,
    undo: projectUndo,
    redo: projectRedo,
    openProjectFile: openFileInProject,
    setCompiler: setProjectCompiler,
  } = project;
  const { scheduleCompile: scheduleWorkspaceCompile } = latexWs;
  const { tryStartScoreGateAudit } = tools;

  // Desktop and mobile PDF panels share one handler so the choice is always persisted.
  const handleCompilerChange = useCallback(
    (value: LatexCompiler) => {
      setProjectCompiler(value);
      if (projectId) {
        updatePaper(projectId, { compiler: value }).catch(() => {});
      }
    },
    [projectId, setProjectCompiler],
  );

  // Unsaved-changes guard: browser leave (beforeunload) and in-app navigation away from this
  // project. The callbacks are stable so the router registers the blocker once.
  const hasUnsavedChangesRef = useLatestRef(project.bootState === "ready" && project.isDirty);
  const shouldBlockLeave = useCallback(
    ({ current, next }: { current: LeaveLocation; next: LeaveLocation }) =>
      hasUnsavedChangesRef.current &&
      (next.pathname !== current.pathname ||
        projectIdOf(next.search) !== projectIdOf(current.search)),
    [hasUnsavedChangesRef],
  );
  const warnBeforeUnload = useCallback(() => hasUnsavedChangesRef.current, [hasUnsavedChangesRef]);
  const leaveBlocker = useBlocker({
    shouldBlockFn: shouldBlockLeave,
    enableBeforeUnload: warnBeforeUnload,
    withResolver: true,
  });

  const handleSave = useCallback(() => {
    if (!projectId) return;
    persistActiveThreadNowRef.current();
    persistProjectFiles({ immediate: true });
    if (projectAutoCompile) {
      scheduleWorkspaceCompile(projectLatex);
    }
  }, [projectId, persistProjectFiles, projectAutoCompile, projectLatex, scheduleWorkspaceCompile]);

  useEffect(() => {
    if (project.bootState !== "ready" || project.showSplash || onboardingScheduledRef.current) {
      return;
    }
    if (hasSeenEditorOnboarding()) return;
    onboardingScheduledRef.current = true;
    const timer = window.setTimeout(() => setOnboardingOpen(true), 450);
    return () => window.clearTimeout(timer);
  }, [project.bootState, project.showSplash]);

  useEffect(() => {
    tryStartScoreGateAudit();
  }, [exportOpen, project.mainLatexSource, tryStartScoreGateAudit]);

  useEffect(() => {
    if (project.bootState !== "ready" || !projectId || !project.autoSave || !project.isDirty) {
      return;
    }
    const timer = window.setTimeout(() => {
      handleSave();
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [project.bootState, projectId, project.autoSave, project.isDirty, project.latex, handleSave]);

  useEffect(() => {
    chatHydratedForProjectRef.current = null;
  }, [projectId]);

  useEffect(() => {
    if (project.bootState !== "ready" || !projectId) return;
    if (chatHydratedForProjectRef.current === projectId) return;
    chatHydratedForProjectRef.current = projectId;
    const persisted = hydrateChatFromProject(project.bootChatThreadsRef.current);
    if (persisted.length < project.bootChatThreadsRef.current.length) {
      persistChatThreads(projectId, persisted);
    }
  }, [project.bootState, hydrateChatFromProject, projectId, project.bootChatThreadsRef]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        handleSave();
        return;
      }
      if (isOtherEditableTarget(e.target)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) projectRedo();
        else projectUndo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        projectRedo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleSave, projectUndo, projectRedo]);

  const openProjectFile = useCallback(
    (path: string) => {
      openFileInProject(path);
      if (isImageAssetFile(path)) {
        setMobileTab("editor");
      }
    },
    [openFileInProject],
  );

  const handleSelectionContextChange = useCallback(
    (payload: { context: EditorSelectionContext; anchor: SelectionAnchor } | null) => {
      setSelectionPick(payload);
    },
    [],
  );

  const openQuickEditFromPick = useCallback(
    (pick: { context: EditorSelectionContext; anchor: SelectionAnchor }) => {
      setChatSelectionContext(pick.context);
      setSelection(pick.context.text);
      setChatComposerMode("quick-edit");
      openChatPanel();
      setSelectionPick(null);
    },
    [openChatPanel, setChatSelectionContext, setChatComposerMode],
  );

  const handleAddSelectionToChat = useCallback(() => {
    if (!selectionPick) return;
    setChatSelectionContext(selectionPick.context);
    setSelection(selectionPick.context.text);
    setChatComposerMode("normal");
    openChatPanel();
    setSelectionPick(null);
  }, [selectionPick, openChatPanel, setChatSelectionContext, setChatComposerMode]);

  const handleQuickEditSelection = useCallback(() => {
    if (!selectionPick) return;
    openQuickEditFromPick(selectionPick);
  }, [selectionPick, openQuickEditFromPick]);

  const handleAskDicoFixCompile = useCallback(() => {
    if (!latexWs.compileError || !latexWs.canAskDicoFixCompile) return;
    setChatComposerMode("quick-edit");
    setChatSelectionContext(null);
    setSelection("");
    setChatInput(shellCopy.fixCompilePrompt(latexWs.compileError.slice(0, 1500)));
    if (latexWs.compileErrorLine) {
      latexWs.setHighlightLine(latexWs.compileErrorLine);
    }
    openChatPanel();
  }, [
    latexWs,
    openChatPanel,
    setChatInput,
    setChatSelectionContext,
    setChatComposerMode,
    shellCopy,
  ]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "k") return;
      const target = e.target as HTMLElement | null;
      if (target?.closest(".latex-input")) return;
      if (!selectionPick?.context.text.trim()) return;
      e.preventDefault();
      handleQuickEditSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectionPick, handleQuickEditSelection]);

  // Stable handlers so the memoized sidebar / center / preview / tools panels skip re-rendering
  // on updates that do not concern them (e.g. every streamed chat token).
  const { fileInputRef, folderInputRef, zipInputRef, assetInputRef } = project;
  const { setToolsOpen } = tools;
  const handleSidebarExpandedChange = useCallback((next: boolean) => {
    setSidebarExpanded(next);
    window.localStorage.setItem(EDITOR_SIDEBAR_STORAGE_KEY, next ? "expanded" : "collapsed");
  }, []);
  const handleUploadClick = useCallback(() => fileInputRef.current?.click(), [fileInputRef]);
  const handleUploadFolderClick = useCallback(
    () => folderInputRef.current?.click(),
    [folderInputRef],
  );
  const handleUploadZipClick = useCallback(() => zipInputRef.current?.click(), [zipInputRef]);
  const handleUploadAssetClick = useCallback(() => assetInputRef.current?.click(), [assetInputRef]);
  const handleDismissSelectionToolbar = useCallback(() => setSelectionPick(null), []);
  const handleToggleTools = useCallback(() => setToolsOpen((v) => !v), [setToolsOpen]);
  const handleCloseTools = useCallback(() => setToolsOpen(false), [setToolsOpen]);
  const handleOpenShare = useCallback(() => setShareOpen(true), []);
  const handleOpenExport = useCallback(() => setExportOpen(true), []);
  const handleOpenDefense = useMemo(
    () => (projectId ? () => void navigate({ to: "/defense", search: { projectId } }) : undefined),
    [navigate, projectId],
  );
  const pdfPreviewProps = useMemo(
    () => ({
      pdfData: latexWs.pdfData,
      isCompiling: latexWs.isCompiling,
      compileError: latexWs.compileError,
      compileWarning: latexWs.compileWarning,
      compileLog: latexWs.compileLog,
      synctexBase64: latexWs.synctexBase64,
      pdfBase64: latexWs.pdfBase64,
      mainFile: project.mainFile,
      compiler: project.compiler,
      onSynctexHit: latexWs.handleSynctexHit,
      onCompile: () => void latexWs.handleCompile(),
      onAskDicoFix: latexWs.canAskDicoFixCompile ? handleAskDicoFixCompile : undefined,
      compileCacheId: projectId,
      projectName: project.projectName,
      latexSource: project.mainLatexSource,
    }),
    [
      latexWs,
      projectId,
      project.mainFile,
      project.compiler,
      project.projectName,
      project.mainLatexSource,
      handleAskDicoFixCompile,
    ],
  );

  const toolsPanelBindings = useMemo(
    () => ({
      ...tools.toolsPanelProps,
      logicAuditScopeHint,
      logicAuditProgressDetail: auditInProgress
        ? formatLogicAuditProgress(chatStreamProgress)
        : null,
      preflightReport: preflight.report,
      preflightLoading: preflight.loading,
      preflightError: preflight.error,
      preflightProfile: preflight.profile,
      onPreflightProfileChange: preflight.setProfile,
      onRunPreflight: preflight.runPreflight,
      onJumpToPreflightFinding: preflight.jumpToFinding,
      canJumpToPreflightFinding: preflight.canJumpToFinding,
    }),
    [
      tools.toolsPanelProps,
      auditInProgress,
      chatStreamProgress,
      logicAuditScopeHint,
      preflight.report,
      preflight.loading,
      preflight.error,
      preflight.profile,
      preflight.setProfile,
      preflight.runPreflight,
      preflight.jumpToFinding,
      preflight.canJumpToFinding,
    ],
  );

  return (
    <div className="editor-shell flex h-[100dvh] w-full flex-col overflow-hidden bg-background text-foreground">
      {project.uploadStatus && (
        <div className="upload-blocking-overlay">
          <div className="upload-blocking-card">
            <p className="upload-blocking-msg">{project.uploadStatus}</p>
            <div
              className="upload-progress-track"
              role="progressbar"
              aria-label={project.uploadStatus}
            >
              <div className="upload-progress-bar" />
            </div>
          </div>
        </div>
      )}
      <ConfirmDialog
        open={leaveBlocker.status === "blocked"}
        onOpenChange={(open) => {
          if (!open) leaveBlocker.reset?.();
        }}
        title={shellCopy.unsavedLeave.title}
        description={shellCopy.unsavedLeave.body}
        confirmLabel={shellCopy.unsavedLeave.leave}
        cancelLabel={shellCopy.unsavedLeave.stay}
        destructive
        onConfirm={() => leaveBlocker.proceed?.()}
      />
      {project.bootState === "error" && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
          <p className="font-serif-body text-lg font-semibold">{shellCopy.bootError.title}</p>
          <p className="max-w-md text-sm text-muted-foreground">{project.bootError}</p>
          <div className="flex flex-wrap justify-center gap-2">
            <button
              type="button"
              onClick={project.retryBootLoad}
              className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
            >
              {shellCopy.bootError.retry}
            </button>
            <Link
              to="/projects"
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              {shellCopy.bootError.backToProjects}
            </Link>
          </div>
        </div>
      )}
      {project.bootState !== "error" && project.showSplash && (
        <EditorEntrySplash
          exiting={project.splashPhase === "exiting"}
          label={project.bootState === "loading" ? shell.loadingProject : shell.openingEditor}
        />
      )}
      {project.bootState !== "error" && project.showEditor && (
        <div
          className={`flex min-h-0 flex-1 flex-col overflow-hidden${
            project.showSplash ? " invisible" : ""
          }`}
        >
          <EdicoMasthead
            integrityStrictness={project.integrityStrictness}
            className="hidden md:flex"
          />
          <MobileHeader
            projectName={project.projectName}
            onUpload={() => project.fileInputRef.current?.click()}
            onExport={() => setExportOpen(true)}
            exportEnabled={Boolean(latexWs.pdfData)}
          />
          <MobileTabBar tab={mobileTab} onChange={setMobileTab} />

          <input
            ref={project.zipInputRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={project.handleZipImport}
          />
          <input
            ref={project.fileInputRef}
            type="file"
            accept=".tex,.latex,.png,.jpg,.jpeg,.gif,.webp,.svg,.pdf,.eps,.cls,.bst,.sty,.bib"
            multiple
            className="hidden"
            onChange={project.handleUpload}
          />
          <input
            ref={project.folderInputRef}
            type="file"
            multiple
            className="hidden"
            {...({ webkitdirectory: "", directory: "" } as InputHTMLAttributes<HTMLInputElement>)}
            onChange={project.handleUpload}
          />
          <input
            ref={project.assetInputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.gif,.webp,.svg,.pdf,.eps,.cls,.bst,.sty,.bib"
            multiple
            className="hidden"
            onChange={project.handleAssetUpload}
          />

          <div className="hidden md:flex flex-1 min-h-0 overflow-hidden">
            <LeftSidebar
              projectName={project.projectName}
              outlineLatex={project.mainLatexSource}
              highlightLine={latexWs.highlightLine}
              onRenameProject={project.handleRenameProject}
              onOutlineJump={latexWs.jumpToOutlineLine}
              files={project.projectFiles}
              activeFile={project.activeFile}
              mainFile={project.mainFile}
              assets={project.assets}
              tab={sidebarTab}
              onTabChange={setSidebarTab}
              expanded={sidebarExpanded}
              onExpandedChange={handleSidebarExpandedChange}
              onSelectFile={openProjectFile}
              onUpload={handleUploadClick}
              onUploadFolder={handleUploadFolderClick}
              onUploadZip={handleUploadZipClick}
              onUploadAsset={handleUploadAssetClick}
              isDirty={project.isDirty}
              chatThreads={chatThreads}
              activeChatId={activeChatId}
              onNewChat={handleNewChat}
              onSwitchChat={handleSwitchChat}
              onRenameChat={handleRenameChat}
              onDeleteChat={handleDeleteChat}
            />
            <EditorDesktopPanels
              center={
                <CenterPanel
                  latex={project.latex}
                  activeFile={project.activeFile}
                  activeAsset={project.activeAsset}
                  viewingAsset={project.viewingAsset}
                  highlightLine={latexWs.highlightLine}
                  synctexHighlight={latexWs.synctexHighlight}
                  editorRef={latexEditorRef}
                  onLatexChange={project.setLatex}
                  onSelectionChange={setSelection}
                  onSelectionContextChange={handleSelectionContextChange}
                  selectionPick={selectionPick}
                  onAddSelectionToChat={handleAddSelectionToChat}
                  onQuickEditSelection={handleQuickEditSelection}
                  onDismissSelectionToolbar={handleDismissSelectionToolbar}
                  onQuickEditRequest={openQuickEditFromPick}
                  chatOpen={chatOpen}
                  toolsOpen={tools.toolsOpen}
                  onToggleTools={handleToggleTools}
                  onShare={handleOpenShare}
                  onExport={handleOpenExport}
                  onDefense={handleOpenDefense}
                  exportEnabled={Boolean(latexWs.pdfData)}
                  shareEnabled={Boolean(project.shareStatus?.enabled)}
                  pendingEdits={pendingEdits}
                  activeEditId={activeEditId}
                  onSelectEdit={setActiveEditId}
                  onAcceptEdit={handleAcceptEdit}
                  onRejectEdit={handleRejectEdit}
                  onAcceptAllEdits={handleAcceptAllEdits}
                  onRejectAllEdits={handleRejectAllEdits}
                  mainFile={project.mainFile}
                  resolveFileContent={resolveFileContent}
                  {...chatProps}
                />
              }
              right={
                tools.toolsOpen ? (
                  <ToolsPanel
                    latex={project.mainLatexSource}
                    projectId={projectId ?? ""}
                    autoCompile={project.autoCompile}
                    onAutoCompileChange={project.setAutoCompile}
                    onRunLogicAudit={runLogicAuditFromPanel}
                    logicAuditLoading={auditInProgress}
                    logicAuditSectionProgress={auditSectionProgress}
                    onCancelLogicAudit={handleStopChat}
                    onClose={handleCloseTools}
                    {...toolsPanelBindings}
                  />
                ) : (
                  <PanelErrorBoundary
                    panel="pdf"
                    resetKeys={[latexWs.pdfData]}
                    fallbackClassName="h-full"
                  >
                    <PdfPreviewPanel {...pdfPreviewProps} onCompilerChange={handleCompilerChange} />
                  </PanelErrorBoundary>
                )
              }
            />
          </div>

          <div className="flex md:hidden flex-1 min-h-0 flex-col overflow-hidden">
            {mobileTab === "files" && (
              <MobileFilesPanel
                projectName={project.projectName}
                outlineLatex={project.mainLatexSource}
                highlightLine={latexWs.highlightLine}
                onRenameProject={project.handleRenameProject}
                onOutlineJump={latexWs.jumpToOutlineLine}
                files={project.projectFiles}
                activeFile={project.activeFile}
                mainFile={project.mainFile}
                assets={project.assets}
                onSelectFile={openProjectFile}
                onUpload={() => project.fileInputRef.current?.click()}
                onUploadFolder={() => project.folderInputRef.current?.click()}
                onUploadZip={() => project.zipInputRef.current?.click()}
                isDirty={project.isDirty}
                chatThreads={chatThreads}
                activeChatId={activeChatId}
                onNewChat={handleNewChat}
                onSwitchChat={(id) => {
                  handleSwitchChat(id);
                  setMobileChatOpen(true);
                }}
                onRenameChat={handleRenameChat}
                onDeleteChat={handleDeleteChat}
              />
            )}
            {mobileTab === "editor" && (
              <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
                {project.viewingAsset ? (
                  project.activeAsset ? (
                    <ProjectAssetPreview path={project.activeFile} asset={project.activeAsset} />
                  ) : (
                    <div className="project-asset-preview-missing p-6 text-sm text-muted-foreground">
                      {editorCopy(locale).assetPreview.missing}
                    </div>
                  )
                ) : (
                  <>
                    <LatexEditor
                      editorRef={latexEditorRef}
                      latex={project.latex}
                      onLatexChange={project.setLatex}
                      onSelectionChange={setSelection}
                      onSelectionContextChange={handleSelectionContextChange}
                      onQuickEditRequest={openQuickEditFromPick}
                      fullHeight
                      highlightLine={latexWs.highlightLine}
                      synctexHighlight={latexWs.synctexHighlight}
                      inlineSuggestion={inlineSuggestion}
                    />
                    {selectionPick && (
                      <EditorSelectionToolbar
                        context={selectionPick.context}
                        anchor={selectionPick.anchor}
                        copy={t.selectionToolbar}
                        onAskSelection={handleAddSelectionToChat}
                        onEditSelection={handleQuickEditSelection}
                        onDismiss={() => setSelectionPick(null)}
                      />
                    )}
                    {pendingEdits?.length ? (
                      <PendingEditsPanel
                        pendingEdits={pendingEdits}
                        activeEditId={activeEditId}
                        mainFile={project.mainFile}
                        resolveFileContent={resolveFileContent}
                        onSelectEdit={setActiveEditId}
                        onAcceptEdit={handleAcceptEdit}
                        onRejectEdit={handleRejectEdit}
                        onAcceptAll={handleAcceptAllEdits}
                        onRejectAll={handleRejectAllEdits}
                      />
                    ) : pendingSuggestion ? (
                      <SuggestionPanel
                        originalText={pendingSuggestion.originalText}
                        suggestion={pendingSuggestion.suggestion}
                        diff={pendingSuggestion.diff}
                        flags={pendingSuggestion.flags}
                        applyMode={pendingSuggestion.applyMode}
                        onAccept={handleAcceptSuggestion}
                        onReject={handleRejectSuggestion}
                      />
                    ) : null}
                  </>
                )}
              </div>
            )}
            {mobileTab === "preview" && (
              <PanelErrorBoundary
                panel="pdf"
                resetKeys={[latexWs.pdfData]}
                fallbackClassName="flex-1"
              >
                <PdfPreviewPanel
                  {...pdfPreviewProps}
                  onCompilerChange={handleCompilerChange}
                  mobile
                />
              </PanelErrorBoundary>
            )}
          </div>

          <MobileBottomBar
            activeFile={project.activeFile}
            onOpenFiles={() => setMobileTab("files")}
            onOpenTools={() => setMobileToolsOpen(true)}
            onOpenChat={() => setMobileChatOpen(true)}
            isDirty={project.isDirty}
          />
          {mobileChatOpen && (
            <MobileChatSheet onClose={() => setMobileChatOpen(false)} {...chatProps} />
          )}
          {mobileToolsOpen && projectId && (
            <MobileToolsSheet
              onClose={() => setMobileToolsOpen(false)}
              latex={project.mainLatexSource}
              projectId={projectId}
              autoCompile={project.autoCompile}
              onAutoCompileChange={project.setAutoCompile}
              onRunLogicAudit={runLogicAuditFromPanel}
              logicAuditLoading={auditInProgress}
              logicAuditSectionProgress={auditSectionProgress}
              onCancelLogicAudit={handleStopChat}
              {...toolsPanelBindings}
            />
          )}

          <StatusBar lineCount={statusLineCount} className="hidden md:flex" />
          {projectId ? (
            <ShareLinkDialog
              open={shareOpen}
              onOpenChange={setShareOpen}
              paperId={projectId}
              onStatusChange={project.setShareStatus}
            />
          ) : null}
          <PaperScoreDownloadDialog
            open={exportOpen}
            onOpenChange={setExportOpen}
            projectName={project.projectName}
            latex={project.mainLatexSource}
            pdfData={latexWs.pdfData}
            citationResults={toolsPanelBindings.citationResults}
            paperId={projectId}
            {...tools.exportDialogProps}
          />
          <EditorOnboardingDialog open={onboardingOpen} onOpenChange={setOnboardingOpen} />
        </div>
      )}
    </div>
  );
}
