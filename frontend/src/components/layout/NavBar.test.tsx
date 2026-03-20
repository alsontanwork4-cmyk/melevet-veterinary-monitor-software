// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { NavBar } from "./NavBar";


let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.innerHTML = "";
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
});

describe("NavBar", () => {
  it("shows Homepage and Decoding links and marks Homepage active at root", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/"]}>
          <NavBar isOpen onToggle={() => undefined} userDisplayName="Dr Tan" onLogout={() => undefined} />
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain("Homepage");
    expect(container.textContent).toContain("Decoding");
    expect(container.textContent).not.toContain("Settings");
    expect(container.textContent).not.toContain("Help");

    const links = Array.from(container.querySelectorAll("a"));
    const homepageLink = links.find((link) => link.textContent?.trim() === "Homepage");
    expect(homepageLink?.className).toContain("nav-link-active");
    expect(container.textContent).toContain("Dr Tan");
    expect(container.textContent).toContain("Sign out");
  });

  it("opens settings and help from the gear menu", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/activity"]}>
          <NavBar isOpen onToggle={() => undefined} userDisplayName="Dr Tan" onLogout={() => undefined} />
        </MemoryRouter>,
      );
    });

    const menuButton = container.querySelector('button[aria-label="Open settings and help menu"]');
    expect(menuButton).not.toBeNull();

    await act(async () => {
      menuButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const menu = container.querySelector('[role="menu"][aria-label="Settings and help"]');
    expect(menu).not.toBeNull();
    expect(menu?.textContent).toContain("Settings");
    expect(menu?.textContent).toContain("Help");
  });
});
