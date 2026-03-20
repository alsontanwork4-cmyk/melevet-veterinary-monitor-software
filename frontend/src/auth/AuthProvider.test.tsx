// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./AuthProvider";
import { getAuthSession, loginWithPassword } from "../api/endpoints";

vi.mock("../api/endpoints", () => ({
  getAuthSession: vi.fn(),
  loginWithPassword: vi.fn(),
  logoutCurrentSession: vi.fn(),
}));

vi.mock("../runtime", () => ({
  isLocalAppMode: false,
  localAppUserName: "Local workstation",
}));

type Deferred<T> = {
  promise: Promise<T>;
  reject: (reason?: unknown) => void;
  resolve: (value: T | PromiseLike<T>) => void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

function buildSession() {
  return {
    user: {
      id: 1,
      username: "admin",
    },
    csrf_token: "csrf-token",
    expires_at: "2026-03-12T02:47:12.034384Z",
  };
}

function buildAxiosError(message: string, status?: number) {
  return {
    isAxiosError: true,
    message,
    response: status
      ? {
          status,
          data: { detail: message },
        }
      : undefined,
  };
}

function AuthHarness() {
  const { errorMessage, isSubmitting, login, status, user } = useAuth();

  return (
    <div>
      <div data-testid="status">{status}</div>
      <div data-testid="user">{user?.username ?? ""}</div>
      <div data-testid="error">{errorMessage ?? ""}</div>
      <div data-testid="submitting">{String(isSubmitting)}</div>
      <button
        type="button"
        onClick={() => {
          void login({ username: "admin", password: "admin" }).catch(() => undefined);
        }}
      >
        Sign in
      </button>
    </div>
  );
}

const mockedGetAuthSession = vi.mocked(getAuthSession);
const mockedLoginWithPassword = vi.mocked(loginWithPassword);

let container: HTMLDivElement;
let root: Root;

async function flushAsyncWork() {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

async function waitFor(assertion: () => void) {
  const startedAt = Date.now();
  while (true) {
    try {
      assertion();
      return;
    } catch (error) {
      if (Date.now() - startedAt > 3000) {
        throw error;
      }
      await flushAsyncWork();
    }
  }
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.innerHTML = "";
  document.body.appendChild(container);
  root = createRoot(container);

  vi.clearAllMocks();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
});

describe("AuthProvider", () => {
  it("ignores a stale bootstrap failure after a successful login and does not force a second session refresh", async () => {
    const bootstrap = createDeferred<ReturnType<typeof buildSession>>();
    mockedGetAuthSession.mockImplementation(() => bootstrap.promise as Promise<ReturnType<typeof buildSession>>);
    mockedLoginWithPassword.mockResolvedValue(buildSession());

    await act(async () => {
      root.render(
        <AuthProvider>
          <AuthHarness />
        </AuthProvider>,
      );
    });

    const button = container.querySelector("button");
    expect(button).not.toBeNull();

    await act(async () => {
      button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(container.querySelector('[data-testid="status"]')?.textContent).toBe("authenticated");
      expect(container.querySelector('[data-testid="user"]')?.textContent).toBe("admin");
    });

    bootstrap.reject(buildAxiosError("Authentication required", 401));
    await flushAsyncWork();

    expect(container.querySelector('[data-testid="status"]')?.textContent).toBe("authenticated");
    expect(container.querySelector('[data-testid="user"]')?.textContent).toBe("admin");
    expect(mockedGetAuthSession).toHaveBeenCalledTimes(1);
  });

  it("surfaces backend auth detail for invalid credentials", async () => {
    mockedGetAuthSession.mockRejectedValue(buildAxiosError("Authentication required", 401));
    mockedLoginWithPassword.mockRejectedValue(buildAxiosError("Invalid username or password", 401));

    await act(async () => {
      root.render(
        <AuthProvider>
          <AuthHarness />
        </AuthProvider>,
      );
    });

    const button = container.querySelector("button");
    expect(button).not.toBeNull();

    await act(async () => {
      button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(container.querySelector('[data-testid="error"]')?.textContent).toBe("Invalid username or password");
      expect(container.querySelector('[data-testid="status"]')?.textContent).toBe("unauthenticated");
    });
  });

  it("falls back to a transport-safe message when the server cannot be reached", async () => {
    mockedGetAuthSession.mockRejectedValue(buildAxiosError("Authentication required", 401));
    mockedLoginWithPassword.mockRejectedValue({
      isAxiosError: true,
      message: "Network Error",
      response: undefined,
    });

    await act(async () => {
      root.render(
        <AuthProvider>
          <AuthHarness />
        </AuthProvider>,
      );
    });

    const button = container.querySelector("button");
    expect(button).not.toBeNull();

    await act(async () => {
      button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(container.querySelector('[data-testid="error"]')?.textContent).toBe("Unable to reach the server right now.");
    });
  });
});
