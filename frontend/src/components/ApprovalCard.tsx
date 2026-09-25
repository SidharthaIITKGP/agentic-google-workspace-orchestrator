import { CalendarCheck, Check, Clock3, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { ApiError, approveAction, rejectAction } from "../api/client";
import type { ApprovalResult, JsonObject, JsonValue, PendingApproval } from "../api/types";
import { SafeLinks } from "./SafeLinks";

type ApprovalState = "pending" | "approving" | "rejecting" | "approved" | "rejected" | "processed";

function previewRows(proposal?: JsonObject): [string, string][] {
  if (!proposal) return [];
  const nested = proposal.arguments;
  const source = nested && typeof nested === "object" && !Array.isArray(nested) ? nested : proposal;
  const labels: Record<string, string> = { title: "Title", start: "Starts", end: "Ends", attendees: "Attendees", create_google_meet: "Google Meet", operation: "Action" };
  const rows: [string, string][] = [];
  if (typeof proposal.operation === "string") rows.push([labels.operation, proposal.operation.replaceAll("_", " ")]);
  Object.entries(source).forEach(([key, value]) => {
    if (!(key in labels) || key === "operation") return;
    if (key === "create_google_meet") rows.push([labels[key], value === true ? "Requested" : "No"]);
    else if (Array.isArray(value)) rows.push([labels[key], value.slice(0, 5).map(String).join(", ")]);
    else if (typeof value === "string") rows.push([labels[key], value]);
  });
  return rows;
}

export function ApprovalCard({ approval, onUnauthorized }: { approval: PendingApproval; onUnauthorized: () => void }) {
  const [state, setState] = useState<ApprovalState>("pending");
  const [result, setResult] = useState<ApprovalResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rows = previewRows(approval.proposed_action);
  const approvalId = String(approval.approval_id ?? "");

  async function decide(decision: "approve" | "reject") {
    setState(decision === "approve" ? "approving" : "rejecting");
    setError(null);
    try {
      if (!approvalId) throw new Error("The approval response did not include an approval ID.");
      const response = decision === "approve" ? await approveAction(approvalId) : await rejectAction(approvalId);
      setResult(response);
      setState(decision === "approve" ? "approved" : "rejected");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) onUnauthorized();
      if (caught instanceof ApiError && caught.status === 409) setState("processed");
      else {
        setError(caught instanceof Error ? caught.message : "The action could not be processed.");
        setState("pending");
      }
    }
  }

  const disabled = state !== "pending";
  return (
    <section className="approval-card" aria-label="Action requires approval">
      <div className="approval-heading"><span><ShieldAlert size={18} /></span><div><strong>Action requires approval</strong><small>Review before the orchestrator writes to Google Workspace.</small></div></div>
      <div className="approval-action"><CalendarCheck size={19} /><div><strong>Proposed Workspace action</strong><small>Step {approval.step_id} · {approvalId ? approvalId.slice(0, 8) : "ID unavailable"}</small></div></div>
      {rows.length ? <dl className="approval-preview">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : <p className="preview-unavailable">Detailed preview was not included by the API. Approval still executes the backend’s stored, immutable proposal.</p>}
      {error && <div className="inline-error" role="alert">{error}</div>}
      {state === "approved" && <div className="decision-state success"><Check size={15} /> Approved and executed</div>}
      {state === "rejected" && <div className="decision-state"><X size={15} /> Rejected</div>}
      {state === "processed" && <div className="decision-state"><Clock3 size={15} /> This action was already processed</div>}
      {result && <SafeLinks value={result as unknown as JsonValue} />}
      <div className="approval-buttons">
        <button className="secondary-button" disabled={disabled} onClick={() => decide("reject")}><X size={16} />{state === "rejecting" ? "Rejecting…" : "Reject"}</button>
        <button className="primary-button" disabled={disabled} onClick={() => decide("approve")}><Check size={16} />{state === "approving" ? "Approving…" : "Approve"}</button>
      </div>
    </section>
  );
}
