import { useCallback, useEffect, useState } from "react";
import { ApiError, getSyncStatus, googleLoginUrl, queryWorkspace, triggerSync } from "./api/client";
import type { SyncStatusResponse } from "./api/types";
import { AuthScreen } from "./components/AuthScreen";
import { ChatPanel } from "./components/ChatPanel";
import { ErrorBanner } from "./components/ErrorBanner";
import type { ChatMessage } from "./components/MessageBubble";
import { Sidebar } from "./components/Sidebar";

type AuthState = "checking" | "authenticated" | "unauthenticated";
const conversationStorageKey = "workspace-orchestrator.conversation-id";

function messageId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `message-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function App() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [authBusy, setAuthBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(() => sessionStorage.getItem(conversationStorageKey));

  const refreshSession = useCallback(async () => {
    try {
      const status = await getSyncStatus();
      setSyncStatus(status);
      setAuth("authenticated");
      return true;
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        setAuth("unauthenticated");
        return false;
      }
      setAuth("unauthenticated");
      setError(caught instanceof Error ? caught.message : "Unable to check your session.");
      return false;
    }
  }, []);

  useEffect(() => { void refreshSession(); }, [refreshSession]);

  function requireLogin() {
    setAuth("unauthenticated");
    setError("Your session ended. Reconnect with Google to continue.");
  }

  async function beginLogin() {
    setAuthBusy(true);
    setError(null);
    const popup = window.open(googleLoginUrl(), "google-workspace-oauth", "popup,width=560,height=720");
    if (!popup) {
      setAuthBusy(false);
      setError("Allow popups for this site, then try again.");
      return;
    }
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      if (await refreshSession()) {
        popup.close();
        setAuthBusy(false);
        return;
      }
      if (popup.closed) break;
    }
    setAuthBusy(false);
    setError("Google sign-in was not completed. You can try again safely.");
  }

  async function send(prompt = input) {
    const query = prompt.trim();
    if (!query || loading) return;
    setInput("");
    setError(null);
    setLoading(true);
    setMessages((current) => [...current, { id: messageId(), role: "user", text: query }]);
    const started = performance.now();
    try {
      const response = await queryWorkspace({ query, conversation_id: conversationId });
      setConversationId(response.conversation_id);
      sessionStorage.setItem(conversationStorageKey, response.conversation_id);
      setMessages((current) => [...current, {
        id: messageId(),
        role: "assistant",
        text: response.response,
        response,
        elapsedMs: performance.now() - started,
      }]);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) requireLogin();
      else setError(caught instanceof Error ? caught.message : "The request could not be completed.");
    } finally {
      setLoading(false);
    }
  }

  async function syncNow() {
    if (syncing) return;
    setSyncing(true);
    setError(null);
    try {
      await triggerSync();
      for (let attempt = 0; attempt < 7; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        const status = await getSyncStatus();
        setSyncStatus(status);
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) requireLogin();
      else setError(caught instanceof Error ? caught.message : "Sync could not be requested.");
    } finally {
      setSyncing(false);
    }
  }

  if (auth === "checking") return <div className="app-loading"><span className="brand-mark">✦</span><p>Connecting to your workspace…</p></div>;
  if (auth === "unauthenticated") return <AuthScreen busy={authBusy} error={error} onLogin={() => void beginLogin()} />;

  return <div className="app-shell">
    <Sidebar syncStatus={syncStatus} syncing={syncing} onSync={() => void syncNow()} />
    <ChatPanel messages={messages} input={input} loading={loading} onInput={setInput} onSend={(prompt) => void send(prompt)} onUnauthorized={requireLogin} />
    {error && <ErrorBanner message={error} onClose={() => setError(null)} />}
  </div>;
}
