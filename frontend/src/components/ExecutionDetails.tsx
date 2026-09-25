import { AlertTriangle, Check, ChevronDown, Clock3, Search, SkipForward } from "lucide-react";
import type { ActionTaken, ExecutionError, PendingApproval } from "../api/types";

type Props = { actions: ActionTaken[]; errors: ExecutionError[]; approvals: PendingApproval[] };

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

export function ExecutionDetails({ actions, errors, approvals }: Props) {
  if (!actions.length && !errors.length && !approvals.length) return null;
  return (
    <details className="execution-details">
      <summary><span><Search size={15} /> Execution details</span><ChevronDown size={16} /></summary>
      <div className="execution-list">
        {actions.map((action) => <div className="execution-row" key={action.step_id}><span className="status-icon completed"><Check size={13} /></span><span>{actionLabel(action)}</span><small>completed</small></div>)}
        {approvals.map((approval) => <div className="execution-row" key={approval.approval_id}><span className="status-icon waiting"><Clock3 size={13} /></span><span>Step {approval.step_id}</span><small>awaiting approval</small></div>)}
        {errors.map((error) => <div className="execution-row" key={error.step_id}><span className={`status-icon ${error.status}`}>
          {error.status === "skipped" ? <SkipForward size={13} /> : <AlertTriangle size={13} />}
        </span><span>Step {error.step_id}</span><small>{error.status}</small></div>)}
        <div className="execution-row synthesis"><span className="status-icon completed"><Check size={13} /></span><span>Response synthesized</span></div>
      </div>
    </details>
  );
}
