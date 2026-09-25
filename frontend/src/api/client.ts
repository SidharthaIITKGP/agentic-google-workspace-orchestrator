import type { ApprovalResult, QueryRequest, QueryResponse, SyncStatusResponse } from "./types";

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, "Could not reach the orchestrator backend.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
    const detail = typeof payload?.detail === "string" ? payload.detail : defaultMessage(response.status);
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function defaultMessage(status: number): string {
  if (status === 401) return "Your Google Workspace session has expired.";
  if (status === 403) return "You do not have permission to perform this action.";
  if (status === 409) return "This approval has already been processed.";
  if (status === 422) return "The request could not be validated.";
  return status >= 500 ? "The orchestrator encountered a server error." : "The request failed.";
}

export async function queryWorkspace(payload: QueryRequest): Promise<QueryResponse> {
  const response = await request<Partial<QueryResponse>>("/api/v1/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (
    typeof response.response !== "string"
    || typeof response.conversation_id !== "string"
    || !response.intent
  ) {
    throw new ApiError(502, "The orchestrator returned an incomplete response.");
  }
  const actions = Array.isArray(response.actions_taken)
    ? response.actions_taken.filter(
        (action): action is QueryResponse["actions_taken"][number] =>
          Boolean(action)
          && typeof action.step_id === "string"
          && Boolean(action.data)
          && typeof action.data === "object"
          && !Array.isArray(action.data),
      )
    : [];
  const approvals = Array.isArray(response.pending_approvals)
    ? response.pending_approvals.filter(
        (approval): approval is QueryResponse["pending_approvals"][number] =>
          Boolean(approval)
          && typeof approval.step_id === "string"
          && typeof approval.approval_id === "string",
      )
    : [];
  const errors = Array.isArray(response.errors)
    ? response.errors.filter(
        (error): error is QueryResponse["errors"][number] =>
          Boolean(error)
          && typeof error.step_id === "string"
          && typeof error.status === "string",
      )
    : [];
  return {
    response: response.response,
    conversation_id: response.conversation_id,
    execution_id: response.execution_id ?? null,
    intent: {
      ...response.intent,
      required_services: Array.isArray(response.intent.required_services)
        ? response.intent.required_services
        : [],
      extracted_entities: response.intent.extracted_entities ?? {},
      requires_clarification: response.intent.requires_clarification === true,
    },
    actions_taken: actions,
    pending_approvals: approvals,
    errors,
  };
}

export function approveAction(approvalId: string): Promise<ApprovalResult> {
  return request(`/api/v1/actions/${encodeURIComponent(approvalId)}/approve`, { method: "POST" });
}

export function rejectAction(approvalId: string): Promise<ApprovalResult> {
  return request(`/api/v1/actions/${encodeURIComponent(approvalId)}/reject`, { method: "POST" });
}

export function getSyncStatus(): Promise<SyncStatusResponse> {
  return request("/api/v1/sync/status");
}

export function triggerSync(): Promise<JsonObject> {
  return request("/api/v1/sync/trigger", { method: "POST" });
}

export function googleLoginUrl(): string {
  return `${API_BASE_URL}/api/v1/auth/google`;
}

type JsonObject = { [key: string]: unknown };
