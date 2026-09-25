import { PanelLeftClose, Sparkles } from "lucide-react";
import type { SyncStatusResponse } from "../api/types";
import { SyncStatus } from "./SyncStatus";

type Props = { syncStatus: SyncStatusResponse | null; syncing: boolean; onSync: () => void };

export function Sidebar({ syncStatus, syncing, onSync }: Props) {
  return (
    <aside className="sidebar">
      <header className="sidebar-brand"><div className="brand-mark small"><Sparkles size={18} /></div><div><strong>Orchestrator</strong><small>Google Workspace</small></div><PanelLeftClose size={17} /></header>
      <SyncStatus status={syncStatus} syncing={syncing} onSync={onSync} />
      <footer className="sidebar-footer"><span className="secure-pulse" />Authenticated workspace session</footer>
    </aside>
  );
}
