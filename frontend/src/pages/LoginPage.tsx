import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { isLocalAppMode } from "../runtime";

type LoginFormState = {
  password: string;
  username: string;
};

export function LoginPage() {
  const { errorMessage, isAuthenticated, isSubmitting, login } = useAuth();
  const location = useLocation();
  const [formState, setFormState] = useState<LoginFormState>({
    password: "",
    username: "",
  });

  if (isLocalAppMode) {
    return <Navigate to="/" replace />;
  }

  if (isAuthenticated) {
    const nextPath = typeof location.state === "object" && location.state && "from" in location.state
      ? String((location.state as { from?: string }).from || "/")
      : "/";
    return <Navigate to={nextPath} replace />;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await login(formState);
    } catch {
      // AuthProvider already exposes the most specific safe error message.
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="login-header">
          <p className="login-kicker">Staff Access</p>
          <h1>Sign in to Melevet</h1>
          <p className="helper-text">
            Patient records, uploads, and report exports are now restricted to authenticated staff sessions.
          </p>
        </div>
        <form className="stack-md" onSubmit={handleSubmit}>
          <label>
            Username
            <input
              autoComplete="username"
              name="username"
              value={formState.username}
              onChange={(event) => setFormState((current) => ({ ...current, username: event.target.value }))}
            />
          </label>
          <label>
            Password
            <input
              autoComplete="current-password"
              name="password"
              type="password"
              value={formState.password}
              onChange={(event) => setFormState((current) => ({ ...current, password: event.target.value }))}
            />
          </label>
          {errorMessage ? <p className="error">{errorMessage}</p> : null}
          <button type="submit" disabled={isSubmitting || !formState.username.trim() || !formState.password}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
