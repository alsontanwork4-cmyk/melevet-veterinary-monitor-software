// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewPatientModal } from "./NewPatientModal";

vi.mock("../../api/endpoints", () => ({
  createPatient: vi.fn(),
}));

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
  vi.clearAllMocks();
});

function setInputValue(input: HTMLInputElement, value: string) {
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  valueSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function getInputByLabel(label: string): HTMLInputElement {
  const labels = Array.from(container.querySelectorAll("label"));
  const match = labels.find((node) => node.textContent?.includes(label));
  const input = match?.querySelector("input");
  if (!(input instanceof HTMLInputElement)) {
    throw new Error(`Input not found for label: ${label}`);
  }
  return input;
}

describe("NewPatientModal numeric fields", () => {
  it("keeps only digits in tel and age inputs", async () => {
    await act(async () => {
      root.render(<NewPatientModal open onClose={() => undefined} onCreated={() => undefined} />);
    });

    const telInput = getInputByLabel("Tel");
    const ageInput = getInputByLabel("Age");

    await act(async () => {
      setInputValue(telInput, "65a-12 3");
      setInputValue(ageInput, "1y.5");
    });

    expect(telInput.value).toBe("65123");
    expect(ageInput.value).toBe("15");
  });
});
