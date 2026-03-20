// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./AppShell";

vi.mock("../../auth/AuthProvider", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../../runtime", () => ({
  isLocalAppMode: false,
}));

vi.mock("./NavBar", () => ({
  NavBar: () => <div>Nav</div>,
}));

import { useAuth } from "../../auth/AuthProvider";

const mockedUseAuth = vi.mocked(useAuth);

let container: HTMLDivElement;
let root: Root;

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

describe("AppShell auth redirect", () => {
  it("routes to login instead of showing the protected-shell loading state", async () => {
    mockedUseAuth.mockReturnValue({
      csrfToken: null,
      errorMessage: null,
      isAuthenticated: false,
      isSubmitting: false,
      status: "loading",
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn(),
    });

    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/decode"]}>
          <Routes>
            <Route path="/login" element={<div>Login Screen</div>} />
            <Route path="*" element={<AppShell />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain("Login Screen");
    expect(container.textContent).not.toContain("Checking session");
  });
});
