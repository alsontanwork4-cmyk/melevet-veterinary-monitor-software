import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import axios from "axios";

import {
  getAuthSession,
  loginWithPassword,
  logoutCurrentSession,
} from "../api/endpoints";
import { registerAuthStateHooks } from "../api/client";
import { isLocalAppMode, localAppUserName } from "../runtime";
import type { AuthSession, AuthUser, LoginPayload } from "../types/api";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  csrfToken: string | null;
  errorMessage: string | null;
  isAuthenticated: boolean;
  isSubmitting: boolean;
  status: AuthStatus;
  user: AuthUser | null;
  login: (payload: LoginPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (!error.response) {
      return "Unable to reach the server right now.";
    }
    if (error.response?.status === 401) {
      return "Invalid username or password.";
    }
  }
  return "Unable to complete the request right now.";
}

function isCanceledError(error: unknown): boolean {
  return axios.isCancel(error) || (axios.isAxiosError(error) && error.code === "ERR_CANCELED");
}

function applySessionState(
  session: AuthSession,
  setters: {
    setCsrfToken: (value: string | null) => void;
    setErrorMessage: (value: string | null) => void;
    setStatus: (value: AuthStatus) => void;
    setUser: (value: AuthUser | null) => void;
  },
) {
  setters.setUser(session.user);
  setters.setCsrfToken(session.csrf_token);
  setters.setStatus("authenticated");
  setters.setErrorMessage(null);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(isLocalAppMode ? "authenticated" : "loading");
  const [user, setUser] = useState<AuthUser | null>(
    isLocalAppMode ? { id: 0, username: localAppUserName } : null,
  );
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const csrfTokenRef = useRef<string | null>(null);
  const authRequestVersionRef = useRef(0);

  csrfTokenRef.current = csrfToken;

  function beginAuthRequest() {
    authRequestVersionRef.current += 1;
    return authRequestVersionRef.current;
  }

  function isCurrentAuthRequest(requestVersion: number) {
    return authRequestVersionRef.current === requestVersion;
  }

  function markUnauthenticated(nextErrorMessage: string | null) {
    setUser(null);
    setCsrfToken(null);
    setStatus("unauthenticated");
    setErrorMessage(nextErrorMessage);
  }

  async function refreshSession(signal?: AbortSignal) {
    if (isLocalAppMode) {
      setUser({ id: 0, username: localAppUserName });
      setCsrfToken(null);
      setStatus("authenticated");
      setErrorMessage(null);
      return;
    }
    const requestVersion = beginAuthRequest();
    try {
      const session = await getAuthSession(signal);
      if (signal?.aborted || !isCurrentAuthRequest(requestVersion)) {
        return;
      }
      applySessionState(session, { setCsrfToken, setErrorMessage, setStatus, setUser });
    } catch (error) {
      if (signal?.aborted || isCanceledError(error) || !isCurrentAuthRequest(requestVersion)) {
        return;
      }
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        markUnauthenticated(null);
        return;
      }
      markUnauthenticated(getErrorMessage(error));
    }
  }

  async function login(payload: LoginPayload) {
    if (isLocalAppMode) {
      void payload;
      return;
    }
    const requestVersion = beginAuthRequest();
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const session = await loginWithPassword(payload);
      if (!isCurrentAuthRequest(requestVersion)) {
        return;
      }
      applySessionState(session, { setCsrfToken, setErrorMessage, setStatus, setUser });
    } catch (error) {
      if (isCurrentAuthRequest(requestVersion)) {
        markUnauthenticated(getErrorMessage(error));
      }
      throw error;
    } finally {
      setIsSubmitting(false);
    }
  }

  async function logout() {
    if (isLocalAppMode) {
      return;
    }
    const requestVersion = beginAuthRequest();
    setIsSubmitting(true);
    try {
      await logoutCurrentSession();
    } finally {
      if (isCurrentAuthRequest(requestVersion)) {
        markUnauthenticated(null);
      }
      setIsSubmitting(false);
    }
  }

  useEffect(() => {
    registerAuthStateHooks({
      getCsrfToken: () => csrfTokenRef.current,
      onUnauthorized: () => {
        if (isLocalAppMode) {
          return;
        }
        beginAuthRequest();
        markUnauthenticated(null);
      },
    });

    const controller = new AbortController();
    void refreshSession(controller.signal);

    return () => {
      controller.abort();
      beginAuthRequest();
      registerAuthStateHooks({
        getCsrfToken: () => null,
        onUnauthorized: () => undefined,
      });
    };
  }, []);

  const value: AuthContextValue = {
    csrfToken,
    errorMessage,
    isAuthenticated: status === "authenticated" && user !== null,
    isSubmitting,
    status,
    user,
    login,
    logout,
    refreshSession,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
