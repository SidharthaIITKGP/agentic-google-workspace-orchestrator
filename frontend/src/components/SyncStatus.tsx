import { CalendarDays, HardDrive, Mail, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import type { SyncState, SyncStatusResponse } from "../api/types";

const services = [
  { key: "gmail", label: "Gmail", icon: Mail },
  { key: "google_calendar", label: "Calendar", icon: CalendarDays },
  { key: "google_drive", label: "Drive", icon: HardDrive },
];

function normalizeStatus(payload: SyncStatusResponse | null): Map<string, SyncState> {
  const result = new Map<string, SyncState>();
  if (!payload) return result;
  const candidate = Array.isArray(payload) ? payload : Array.isArray(payload.services) ? payload.services : null;
  if (candidate) {
    candidate.forEach((item) => {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        const record = item as Record<string, unknown>;
        if (typeof record.service === "string") result.set(record.service, record as unknown as SyncState);
      }
    });
    return result;
  }
  Object.entries(payload).forEach(([key, value]) => {
    if (value && typeof value === "object" && !Array.isArray(value)) result.set(key, { service: key, ...(value as object) } as SyncState);
  });
  return result;
}

function stateLabel(value?: SyncState): string {
  if (!value) return "Not synced";
  if (value.status === "running") return "Syncing";
  if (value.status === "failed") return "Failed";
  if (value.status === "completed") return "Synced";
  return value.status || "Not synced";
}

function relativeTime(value?: string | null): string | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

type Props = { status: SyncStatusResponse | null; syncing: boolean; onSync: () => void };

export function SyncStatus({ status, syncing, onSync }: Props) {
  const states = useMemo(() => normalizeStatus(status), [status]);
  return (
    <section className="sync-panel">
      <div className="section-heading"><span>Workspace</span><span className="live-dot">Live</span></div>
      <div className="sync-services">
        {services.map(({ key, label, icon: Icon }) => {
          const state = states.get(key);
          const relative = relativeTime(state?.last_successful_sync);
          return <div className="sync-service" key={key}><Icon size={16} /><div><strong>{label}</strong><small>{stateLabel(state)}{relative ? ` · ${relative}` : ""}</small></div><span className={`state-dot ${state?.status || "unknown"}`} /></div>;
        })}
      </div>
      <button className="sync-button" onClick={onSync} disabled={syncing}><RefreshCw className={syncing ? "spinning" : ""} size={15} />{syncing ? "Sync requested" : "Sync now"}</button>
    </section>
  );
}
