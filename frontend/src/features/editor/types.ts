export type EditorSearch = {
  projectId?: string;
};

export type MobileTab = "files" | "editor" | "preview";

export type PendingSuggestion = {
  file: string;
  originalText: string;
  suggestion: string;
  diff: string;
  flags: { code: string; message: string; severity: string }[];
  revisionId?: string;
  applyMode?: "selection" | "document";
  selectionStart?: number;
  selectionEnd?: number;
  sourceFingerprint?: string;
};

export type PendingEdit = {
  id: string;
  file: string;
  section?: string;
  applyMode: "selection" | "document";
  originalText: string;
  replacementText: string;
  description?: string;
  flags: { code: string; message: string; severity: string }[];
  revisionId?: string;
  accepted?: boolean;
  selectionStart?: number;
  selectionEnd?: number;
  sourceFingerprint?: string;
};

export type ToolsTab =
  "info" | "versions" | "citations" | "logic" | "structure" | "peerReview" | "preflight";
