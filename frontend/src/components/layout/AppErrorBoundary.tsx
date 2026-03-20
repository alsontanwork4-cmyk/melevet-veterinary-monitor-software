import { Component, type ErrorInfo, type ReactNode } from "react";

import { buildApiUrl } from "../../api/client";
import { formatDateTime } from "../../utils/format";

type AppErrorBoundaryProps = {
  children: ReactNode;
};

type AppErrorBoundaryState = {
  error: Error | null;
  crashTimestamp: string | null;
};

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    error: null,
    crashTimestamp: null,
  };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error, crashTimestamp: new Date().toISOString() };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Unhandled application error", error, errorInfo);
    void fetch(buildApiUrl("/telemetry/events"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        event_type: "crash",
        route: window.location.pathname,
        status: "frontend-error-boundary",
        app_version: __APP_VERSION__,
        browser: navigator.userAgent,
        platform: navigator.platform,
        error_name: error.name,
        error_message: error.message,
        stack: error.stack ?? null,
        component_stack: errorInfo.componentStack ?? null,
        metadata: {
          boundary: "AppErrorBoundary",
        },
      }),
    }).catch(() => undefined);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="login-shell">
          <section className="login-card">
            <div className="login-header">
              <p className="login-kicker">Application Error</p>
              <h1>Unable to render the app</h1>
              <p className="helper-text">
                The frontend hit a runtime error before the page finished loading.
              </p>
            </div>
            {this.state.crashTimestamp ? (
              <p className="helper-text">Crash reference: {formatDateTime(this.state.crashTimestamp)}</p>
            ) : null}
            <p className="error">{this.state.error.message}</p>
            <div className="backup-actions">
              <button type="button" className="button-primary" onClick={() => window.location.reload()}>
                Reload app
              </button>
              <a href="/help" className="button-muted">
                Open Help
              </a>
            </div>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
