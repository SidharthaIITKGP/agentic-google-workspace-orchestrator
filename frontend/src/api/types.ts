export type ServiceName = "gmail" | "google_calendar" | "google_drive" | "workspace" | string;
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface Intent {
  intent_name: string;
  required_services: ServiceName[];
  extracted_entities: JsonObject;
  requires_clarification: boolean;
  clarification_question?: string | null;
}

export interface ActionTaken {
  step_id: string;
  data: JsonObject;
}

export interface PendingApproval {
  step_id: string;
  approval_id: string;
  proposed_action?: JsonObject;
}

export interface ExecutionError {
  step_id: string;
  status: "failed" | "skipped" | string;
  error?: { code?: string; message?: string } | null;
}

export interface QueryResponse {
  response: string;
  conversation_id: string;
  execution_id?: string | null;
  intent: Intent;
  actions_taken: ActionTaken[];
  pending_approvals: PendingApproval[];
  errors: ExecutionError[];
}

export interface QueryRequest {
  query: string;
  conversation_id?: string | null;
}

export type SyncState = {
  service: string;
  status: string;
  last_successful_sync?: string | null;
  last_attempted_sync?: string | null;
  error_details?: JsonValue;
};

export type SyncStatusResponse = JsonObject | SyncState[];

export interface ApprovalResult {
  status?: string;
  data?: JsonObject;
  result?: JsonObject;
  [key: string]: JsonValue | JsonObject | undefined;
}
