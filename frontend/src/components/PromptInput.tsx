import { ArrowUp, CornerDownLeft } from "lucide-react";
import { useRef } from "react";

type Props = { value: string; disabled: boolean; onChange: (value: string) => void; onSubmit: () => void };

export function PromptInput({ value, disabled, onChange, onSubmit }: Props) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  function submit() {
    if (!disabled && value.trim()) onSubmit();
  }
  return <div className="composer-wrap"><div className="composer"><textarea ref={textarea} value={value} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
  }} rows={1} placeholder="Ask across Gmail, Calendar, and Drive…" aria-label="Message the orchestrator" disabled={disabled} /><button aria-label="Send message" onClick={submit} disabled={disabled || !value.trim()}><ArrowUp size={18} /></button></div><div className="composer-hint"><span><CornerDownLeft size={12} /> Enter to send</span><span>Shift + Enter for a new line</span></div></div>;
}
