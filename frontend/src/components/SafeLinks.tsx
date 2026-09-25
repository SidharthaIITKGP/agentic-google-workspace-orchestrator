import { ExternalLink } from "lucide-react";
import type { JsonValue } from "../api/types";

const linkKeys = new Set(["html_link", "htmlLink", "meet_url", "meetUrl", "hangoutLink", "web_view_link", "webViewLink"]);

function safeGoogleUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    const allowed = url.protocol === "https:" && (url.hostname === "google.com" || url.hostname.endsWith(".google.com"));
    return allowed ? url.toString() : null;
  } catch {
    return null;
  }
}

export function collectSafeLinks(value: JsonValue, output = new Set<string>()): string[] {
  if (!value || typeof value !== "object") return [...output];
  if (Array.isArray(value)) {
    value.forEach((item) => collectSafeLinks(item, output));
  } else {
    Object.entries(value).forEach(([key, child]) => {
      if (linkKeys.has(key)) {
        const url = safeGoogleUrl(child);
        if (url) output.add(url);
      } else if (child && typeof child === "object") collectSafeLinks(child, output);
    });
  }
  return [...output];
}

export function SafeLinks({ value }: { value: JsonValue }) {
  const links = collectSafeLinks(value);
  if (!links.length) return null;
  return <div className="safe-links">{links.map((url) => (
    <a key={url} href={url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} /> Open in Google Workspace</a>
  ))}</div>;
}
