import { Check, Copy, Sparkles, UserRound } from "lucide-react";
import { useState } from "react";
import type { QueryResponse } from "../api/types";
import { ApprovalCard } from "./ApprovalCard";
import { ExecutionDetails } from "./ExecutionDetails";
import { SafeLinks } from "./SafeLinks";
import { ServiceBadges, servicesFromResponse } from "./ServiceBadges";

export type ChatMessage = { id: string; role: "user" | "assistant"; text: string; response?: QueryResponse; elapsedMs?: number };

export function MessageBubble({ message, onUnauthorized }: { message: ChatMessage; onUnauthorized: () => void }) {
  const [copied, setCopied] = useState(false);
  const response = message.response;
  async function copy() {
    await navigator.clipboard.writeText(message.text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }
  return <article className={`message ${message.role}`}>
    <div className="avatar">{message.role === "assistant" ? <Sparkles size={16} /> : <UserRound size={16} />}</div>
    <div className="message-body"><div className="message-meta"><strong>{message.role === "assistant" ? "Workspace Orchestrator" : "You"}</strong>{message.elapsedMs != null && <small>{(message.elapsedMs / 1000).toFixed(1)}s client time</small>}</div>
      <p>{message.text}</p>
      {response && <>
        <ServiceBadges services={servicesFromResponse(response.intent.required_services, response.actions_taken)} />
        {response.actions_taken.map((action) => <SafeLinks key={action.step_id} value={action.data} />)}
        {response.errors.length > 0 && <div className="partial-warning">Some steps did not complete. Open execution details for status.</div>}
        <ExecutionDetails actions={response.actions_taken} errors={response.errors} approvals={response.pending_approvals} />
        {response.pending_approvals.map((approval) => <ApprovalCard key={approval.approval_id} approval={approval} onUnauthorized={onUnauthorized} />)}
      </>}
      {message.role === "assistant" && <button className="copy-button" onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy"}</button>}
    </div>
  </article>;
}
