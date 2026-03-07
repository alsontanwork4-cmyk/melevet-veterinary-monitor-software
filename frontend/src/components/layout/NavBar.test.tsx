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
          <NavBar />
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain("Homepage");
    expect(container.textContent).toContain("Decoding");

    const links = Array.from(container.querySelectorAll("a"));
    const homepageLink = links.find((link) => link.textContent?.trim() === "Homepage");
    expect(homepageLink?.className).toContain("nav-link-active");
  });
});
