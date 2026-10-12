import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runPreflight, type RunPreflightOptions } from "@/lib/api/preflight-api";

// Hoisted above the imports by vitest. getAccessToken reads localStorage at call time, which
// doesn't exist under vitest's node environment — mock the module instead of shimming the DOM.
vi.mock("@/lib/auth-store", () => ({
  getAccessToken: () => "test-token",
  logoutUser: vi.fn(),
}));

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const baseOptions: RunPreflightOptions = {
  mainFile: "main.tex",
  files: [{ path: "main.tex", content: "\\documentclass{article}" }],
  bibContent: "@article{a,}",
  profile: {
    doubleBlind: true,
    wordLimit: 8000,
    requiredStatements: ["ethics"],
  },
};

describe("runPreflight", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects with the exact NETWORK_ERROR sentinel when fetch throws a plain error", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    let caught: unknown;
    try {
      await runPreflight(baseOptions);
    } catch (error) {
      caught = error;
    }

    // Exact string, not "contains" — api-errors.ts:isNetworkError compares `=== "network_error"`
    // (case-insensitively), so a near-miss sentinel (e.g. "Network error") would silently stop
    // being recognized while every other check (typecheck, lint, this test file existing) stays
    // green.
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("NETWORK_ERROR");
  });

  it("re-throws AbortError unchanged instead of mapping it to NETWORK_ERROR", async () => {
    const abortError = new DOMException("The operation was aborted.", "AbortError");
    fetchMock.mockRejectedValue(abortError);

    let caught: unknown;
    try {
      await runPreflight(baseOptions);
    } catch (error) {
      caught = error;
    }

    // Identity, not just message — a cancelled run must surface as the original AbortError, never
    // as the generic network-failure sentinel.
    expect(caught).toBe(abortError);
    expect((caught as DOMException).name).toBe("AbortError");
  });

  it("sends the request body in snake_case so the backend doesn't 422 it", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        integrity_mode: "strict",
        findings: [],
        counts: {},
        skipped: [],
        suppressed: [],
        unresolved_includes: [],
        no_content: false,
      }),
    );

    await runPreflight(baseOptions);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;

    expect(Object.keys(body).sort()).toEqual(["bib_content", "files", "main_file", "profile"]);
    expect(Object.keys(body.profile as Record<string, unknown>).sort()).toEqual([
      "double_blind",
      "required_statements",
      "word_limit",
    ]);
  });
});
