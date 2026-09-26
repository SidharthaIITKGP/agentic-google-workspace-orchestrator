import { AlertTriangle, Check, ChevronDown, Clock3, Search, SkipForward } from "lucide-react";
import type { ActionTaken, ExecutionError, PendingApproval } from "../api/types";

type DecisionMetadata = {
  decision_provider?: string;
  intent_family?: string;
  confidence?: number;
  fallback_used?: boolean;
  model?: string;
};

type Props = { actions: ActionTaken[]; errors: ExecutionError[]; approvals: PendingApproval[]; decision?: DecisionMetadata | null };

function actionLabel(action: ActionTaken): string {
  const data = action.data;
  const services = data.searched_services;
  if (Array.isArray(services)) {
    const label = services.map(String).map((item) => item === "google_drive" ? "Drive" : item === "gmail" ? "Gmail" : item).join(", ");
    return `Workspace Search — ${label}`;
  }
  if (Array.isArray(data.events)) return "Calendar — event retrieval";
  if (Array.isArray(data.emails)) return "Gmail — email retrieval";
  if (Array.isArray(data.files)) return "Drive — file retrieval";
  if (data.event && typeof data.event === "object") return "Calendar — event action";
  return `Completed step ${action.step_id}`;
}

function rerankingLabel(action: ActionTaken): string | null {
  const value = action.data.reranking;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const provider = value.provider;
  if (provider === "laya") return "Reranking — Laya";
  if (provider === "hybrid_fallback") return "Reranking — Laya → hybrid fallback";
  return null;
}

export function ExecutionDetails({ actions, errors, approvals, decision }: Props) {
  if (!actions.length && !errors.length && !approvals.length && !decision) return null;
  return (
    <details className="execution-details">
      <summary><span><Search size={15} /> Execution details</span><ChevronDown size={16} /></summary>
      <div className="execution-list">
        {decision?.decision_provider && <div className="execution-row"><span className="status-icon completed"><Check size={13} /></span><span>Decision engine — {decision.decision_provider === "laya" ? "Laya" : decision.decision_provider === "groq_fallback" ? "Laya → Groq fallback" : "Groq"}</span><small>{decision.intent_family || "routing"}{typeof decision.confidence === "number" ? ` · ${Math.round(decision.confidence * 100)}%` : ""}</small></div>}
        {actions.map((action) => <div key={action.step_id}><div className="execution-row"><span className="status-icon completed"><Check size={13} /></span><span>{actionLabel(action)}</span><small>completed</small></div>{rerankingLabel(action) && <div className="execution-row"><span className="status-icon completed"><Check size={13} /></span><span>{rerankingLabel(action)}</span><small>experimental</small></div>}</div>)}
        {approvals.map((approval) => <div className="execution-row" key={approval.approval_id}><span className="status-icon waiting"><Clock3 size={13} /></span><span>Step {approval.step_id}</span><small>awaiting approval</small></div>)}
        {errors.map((error) => <div className="execution-row" key={error.step_id}><span className={`status-icon ${error.status}`}>
          {error.status === "skipped" ? <SkipForward size={13} /> : <AlertTriangle size={13} />}
        </span><span>Step {error.step_id}</span><small>{error.status}</small></div>)}
        <div className="execution-row synthesis"><span className="status-icon completed"><Check size={13} /></span><span>Response synthesized</span></div>
      </div>
    </details>
  );
}
