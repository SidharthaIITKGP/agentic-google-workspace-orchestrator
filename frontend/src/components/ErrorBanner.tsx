import { AlertCircle, X } from "lucide-react";

export function ErrorBanner({ message, onClose }: { message: string; onClose: () => void }) {
  return <div className="error-banner" role="alert"><AlertCircle size={17} /><span>{message}</span><button onClick={onClose} aria-label="Dismiss error"><X size={15} /></button></div>;
}
