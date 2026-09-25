import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { QueryResponse } from "../api/types";
import { ApprovalCard } from "./ApprovalCard";
import { ChatPanel } from "./ChatPanel";
import { MessageBubble } from "./MessageBubble";
import { SyncStatus } from "./SyncStatus";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("demo UI", () => {
  it("does not treat the browser auto-scroll result as an effect cleanup", () => {
    const originalScrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = vi.fn(() => ({}) as never);
    const message = { id: "one", role: "user" as const, text: "hello" };
    const view = render(
      <ChatPanel messages={[message]} input="" loading={false} onInput={() => undefined} onSend={() => undefined} onUnauthorized={() => undefined} />,
    );

    expect(() => view.rerender(
      <ChatPanel messages={[message]} input="" loading onInput={() => undefined} onSend={() => undefined} onUnauthorized={() => undefined} />,
    )).not.toThrow();
    view.unmount();
    Element.prototype.scrollIntoView = originalScrollIntoView;
  });

  it("renders a pending approval and calls the approve endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "approved" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ApprovalCard approval={{ step_id: "create", approval_id: "approval-1" }} onUnauthorized={() => undefined} />);

    expect(screen.getByText("Action requires approval")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/actions/approval-1/approve"));
  });

  it("renders an actual pending-query response without exposing raw action data", () => {
    const response: QueryResponse = {
      response: "Meeting creation pending approval.",
      conversation_id: "conversation",
      execution_id: "execution",
      intent: {
        intent_name: "schedule_meeting",
        required_services: ["google_calendar"],
        extracted_entities: {},
        requires_clarification: false,
      },
      actions_taken: [],
      pending_approvals: [{ step_id: "create_meeting", approval_id: "b2dcecc3-e7b9-4325-a6f2-611add37be57" }],
      errors: [],
    };
    render(<MessageBubble message={{ id: "pending", role: "assistant", text: response.response, response }} onUnauthorized={() => undefined} />);
    expect(screen.getByText("Meeting creation pending approval.")).toBeInTheDocument();
    expect(screen.getByText("Action requires approval")).toBeInTheDocument();
  });

  it("calls the reject endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "rejected" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ApprovalCard approval={{ step_id: "create", approval_id: "approval-2" }} onUnauthorized={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/actions/approval-2/reject"));
  });

  it("renders clarification text without interpreting it", () => {
    const response: QueryResponse = {
      response: "Which meeting should I move?",
      conversation_id: "conversation",
      intent: { intent_name: "move_meeting", required_services: ["google_calendar"], extracted_entities: {}, requires_clarification: true, clarification_question: "Which meeting should I move?" },
      actions_taken: [], pending_approvals: [], errors: [],
    };
    render(<MessageBubble message={{ id: "1", role: "assistant", text: response.response, response }} onUnauthorized={() => undefined} />);
    expect(screen.getByText("Which meeting should I move?")).toBeInTheDocument();
  });

  it("renders sync service state and timestamps", () => {
    render(<SyncStatus status={{ gmail: { status: "completed", last_successful_sync: new Date().toISOString() } }} syncing={false} onSync={() => undefined} />);
    expect(screen.getByText("Gmail")).toBeInTheDocument();
    expect(screen.getByText(/Synced · just now/)).toBeInTheDocument();
  });

  it("does not render giant raw payloads in default execution details", () => {
    const secretBody = "RAW_EMAIL_BODY_".repeat(500);
    const response: QueryResponse = {
      response: "One email was found.", conversation_id: "conversation",
      intent: { intent_name: "search", required_services: ["gmail"], extracted_entities: {}, requires_clarification: false },
      actions_taken: [{ step_id: "gmail", data: { emails: [{ body: secretBody }] } }], pending_approvals: [], errors: [],
    };
    render(<MessageBubble message={{ id: "1", role: "assistant", text: response.response, response }} onUnauthorized={() => undefined} />);
    expect(screen.queryByText(secretBody)).not.toBeInTheDocument();
  });

  it("shows reconnect UI after a 401 session check", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401, headers: { "Content-Type": "application/json" } })));
    render(<App />);
    expect(await screen.findByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
  });
});
