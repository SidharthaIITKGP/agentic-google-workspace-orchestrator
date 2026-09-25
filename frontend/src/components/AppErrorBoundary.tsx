import { Component, type ErrorInfo, type ReactNode } from "react";

type State = { failed: boolean; message: string | null };

export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false, message: null };

  static getDerivedStateFromError(error: unknown): State {
    return {
      failed: true,
      message: error instanceof Error ? error.message : "Unknown rendering error",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Workspace UI render failed", error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="fatal-error">
          <section>
            <span>✦</span>
            <h1>The workspace view needs to recover</h1>
            <p>Your backend request was not repeated and no action was approved automatically.</p>
            {this.state.message && <code className="fatal-error-detail">{this.state.message}</code>}
            <button onClick={() => window.location.reload()}>Reload workspace</button>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}
