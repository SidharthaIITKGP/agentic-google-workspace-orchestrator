import { Chrome, ShieldCheck, Sparkles } from "lucide-react";

type Props = {
  busy: boolean;
  error?: string | null;
  onLogin: () => void;
};

export function AuthScreen({ busy, error, onLogin }: Props) {
  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="brand-mark"><Sparkles size={22} /></div>
        <p className="eyebrow">AI workspace assistant</p>
        <h1>Google Workspace<br />Orchestrator</h1>
        <p className="auth-copy">
          Search Gmail, Calendar, and Drive. Coordinate multi-step work with explicit approval for every write.
        </p>
        {error && <div className="inline-error" role="alert">{error}</div>}
        <button className="google-button" onClick={onLogin} disabled={busy}>
          <Chrome size={19} />
          {busy ? "Waiting for Google…" : "Continue with Google"}
        </button>
        <div className="security-note"><ShieldCheck size={15} /> Tokens stay on the backend</div>
      </section>
    </main>
  );
}
