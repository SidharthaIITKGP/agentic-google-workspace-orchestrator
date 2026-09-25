import { Menu, Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";
import type { ChatMessage } from "./MessageBubble";
import { MessageBubble } from "./MessageBubble";
import { PromptInput } from "./PromptInput";
import { StarterPrompts } from "./StarterPrompts";

type Props = { messages: ChatMessage[]; input: string; loading: boolean; onInput: (value: string) => void; onSend: (prompt?: string) => void; onUnauthorized: () => void };

export function ChatPanel({ messages, input, loading, onInput, onSend, onUnauthorized }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);
  return <main className="chat-panel"><header className="chat-header"><button className="mobile-menu" aria-label="Open navigation"><Menu size={20} /></button><div><strong>Workspace Assistant</strong><span><i /> Ready to orchestrate</span></div></header>
    <div className="conversation">{messages.length === 0 ? <StarterPrompts onSelect={(prompt) => onSend(prompt)} /> : <div className="messages">{messages.map((message) => <MessageBubble key={message.id} message={message} onUnauthorized={onUnauthorized} />)}{loading && <div className="thinking"><span className="avatar"><Sparkles size={16} /></span><div><b /><b /><b /></div><small>Planning and executing across your workspace…</small></div>}<div ref={endRef} /></div>}</div>
    <PromptInput value={input} disabled={loading} onChange={onInput} onSubmit={() => onSend()} />
  </main>;
}
