import { CalendarDays, Database, HardDrive, Mail } from "lucide-react";
import type { ActionTaken, ServiceName } from "../api/types";

const serviceMeta = {
  gmail: { label: "Gmail", icon: Mail },
  google_calendar: { label: "Calendar", icon: CalendarDays },
  google_drive: { label: "Drive", icon: HardDrive },
  workspace: { label: "Workspace Search", icon: Database },
};

export function servicesFromResponse(required: ServiceName[], actions: ActionTaken[]): string[] {
  const actual = new Set(required);
  if (actions.some((action) => Array.isArray(action.data.searched_services))) actual.add("workspace");
  return [...actual];
}

export function ServiceBadges({ services }: { services: string[] }) {
  if (!services.length) return null;
  return (
    <div className="service-badges" aria-label="Services used">
      {services.map((service) => {
        const meta = serviceMeta[service as keyof typeof serviceMeta];
        if (!meta) return null;
        const Icon = meta.icon;
        return <span className="service-badge" key={service}><Icon size={13} />{meta.label}</span>;
      })}
    </div>
  );
}
