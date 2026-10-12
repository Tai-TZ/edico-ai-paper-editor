import { useCallback, useEffect, useRef, useState } from "react";

import {
  runPreflight as runPreflightRequest,
  type PreflightFinding,
  type PreflightProfileInput,
  type PreflightReport,
} from "@/lib/api/preflight-api";
import { toUserFacingMessage } from "@/lib/api/api-errors";
import type { UiLanguage } from "@/lib/locale-store";
import type { ProjectFile } from "@/lib/project-store";
import {
  canJumpToPreflightFinding,
  collectPreflightBibContent,
  loadPreflightProfile,
  savePreflightProfile,
} from "@/lib/preflight-panel";

export type UseEditorPreflightOptions = {
  /** `string | undefined` from the route; an unsaved/boot-time project has no id yet. */
  projectId: string | undefined;
  locale: UiLanguage;
  mainFile: string;
  activeFile: string;
  projectFiles: ProjectFile[];
  switchActiveFile: (path: string) => void;
  /** 1-based — see `useLatexWorkspace.ts:299`. */
  jumpToOutlineLine: (line: number) => void;
};

/**
 * State + API wiring for the Submission Preflight panel. Mirrors the shape of the other
 * `useEditor*` hooks (`useEditorTools.ts`'s `jumpToLogicIssue` is the direct precedent for
 * `jumpToFinding`): switch to the finding's own file before asking the editor to scroll, because
 * outline/scroll helpers operate on whichever file is currently active, not on whichever file a
 * finding happens to belong to.
 */
export function useEditorPreflight({
  projectId,
  locale,
  mainFile,
  activeFile,
  projectFiles,
  switchActiveFile,
  jumpToOutlineLine,
}: UseEditorPreflightOptions) {
  // `projectId` is `string | undefined`; the localStorage key needs a plain `string`, and an
  // empty one deliberately disables persistence rather than writing under a shared "" key.
  const paperId = projectId ?? "";

  const [report, setReport] = useState<PreflightReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfileState] = useState<PreflightProfileInput>(() =>
    loadPreflightProfile(paperId),
  );

  const abortRef = useRef<AbortController | null>(null);

  // Switching papers must not leave the previous paper's report (or its declared profile)
  // showing under the new one — a stale critical finding rendered against the wrong manuscript
  // is actively misleading, not just untidy.
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setError(null);
    setReport(null);
    setProfileState(loadPreflightProfile(paperId));
  }, [paperId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const setProfile = useCallback(
    (next: PreflightProfileInput) => {
      setProfileState(next);
      savePreflightProfile(paperId, next);
    },
    [paperId],
  );

  const runPreflight = useCallback(() => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setLoading(true);
    setError(null);

    runPreflightRequest({
      mainFile,
      files: projectFiles,
      // Every `.bib`, not the first one: see `collectPreflightBibContent`.
      bibContent: collectPreflightBibContent(projectFiles),
      profile,
      locale,
      signal: abort.signal,
    })
      .then((next) => {
        if (abort.signal.aborted) return;
        setReport(next);
      })
      .catch((err: unknown) => {
        if (abort.signal.aborted) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setReport(null);
        setError(toUserFacingMessage(err, locale));
      })
      .finally(() => {
        if (abort.signal.aborted) return;
        setLoading(false);
      });
  }, [mainFile, projectFiles, profile, locale]);

  const canJumpToFinding = useCallback(
    (finding: PreflightFinding) => canJumpToPreflightFinding(finding, projectFiles),
    [projectFiles],
  );

  const jumpToFinding = useCallback(
    (finding: PreflightFinding) => {
      if (finding.file && finding.file !== activeFile) {
        switchActiveFile(finding.file);
      }
      if (finding.line != null && canJumpToPreflightFinding(finding, projectFiles)) {
        jumpToOutlineLine(finding.line);
      }
    },
    [activeFile, switchActiveFile, projectFiles, jumpToOutlineLine],
  );

  return {
    report,
    loading,
    error,
    runPreflight,
    profile,
    setProfile,
    jumpToFinding,
    canJumpToFinding,
  };
}
