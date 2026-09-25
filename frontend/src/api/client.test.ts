import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, googleLoginUrl, queryWorkspace } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("uses the existing Google OAuth route", () => {
    expect(googleLoginUrl()).toMatch(/\/api\/v1\/auth\/google$/);
  });

  it("sends the existing conversation_id with credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      response: "ok",
      conversation_id: "conversation-123",
      intent: {
        intent_name: "follow_up",
        required_services: [],
        extracted_entities: {},
        requires_clarification: false,
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await queryWorkspace({ query: "follow up", conversation_id: "conversation-123" });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/query");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(init.body)).toEqual({ query: "follow up", conversation_id: "conversation-123" });
  });

  it("maps a 401 response to an authentication error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401, headers: { "Content-Type": "application/json" } })));
    await expect(queryWorkspace({ query: "hello" })).rejects.toMatchObject({ status: 401 });
  });

  it("drops malformed optional execution entries instead of crashing the chat", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      response: "Meeting creation pending approval.",
      conversation_id: "conversation-123",
      intent: {
        intent_name: "schedule_meeting",
        required_services: ["google_calendar"],
        extracted_entities: {},
        requires_clarification: false,
      },
      actions_taken: [null, { step_id: "bad", data: null }],
      pending_approvals: [null, { step_id: "create", approval_id: "approval-1" }],
      errors: [null],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    const response = await queryWorkspace({ query: "schedule a meeting" });

    expect(response.actions_taken).toEqual([]);
    expect(response.pending_approvals).toEqual([{ step_id: "create", approval_id: "approval-1" }]);
    expect(response.errors).toEqual([]);
  });
});
