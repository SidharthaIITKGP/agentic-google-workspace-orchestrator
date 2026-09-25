import { CalendarDays, FileSearch, Mail, Users } from "lucide-react";

const prompts = [
  { text: "What's on my calendar tomorrow?", icon: CalendarDays },
  { text: "Show my latest unread emails", icon: Mail },
  { text: "Find recent PDFs in my Drive", icon: FileSearch },
  { text: "Prepare me for my next meeting", icon: Users },
];

export function StarterPrompts({ onSelect }: { onSelect: (prompt: string) => void }) {
  return <section className="starter"><div className="starter-icon">✦</div><h2>What can I help you orchestrate?</h2><p>Search and act across your connected Google Workspace.</p><div className="prompt-grid">{prompts.map(({ text, icon: Icon }) => <button key={text} onClick={() => onSelect(text)}><Icon size={18} /><span>{text}</span></button>)}</div></section>;
}
