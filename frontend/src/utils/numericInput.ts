const allowedControlKeys = new Set([
  "Backspace",
  "Delete",
  "Tab",
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "ArrowDown",
  "Home",
  "End",
  "Enter",
]);

export function sanitizeDigits(value: string): string {
  return value.replace(/\D+/g, "");
}

export function shouldAllowNumericKey(event: React.KeyboardEvent<HTMLInputElement>): boolean {
  if (event.ctrlKey || event.metaKey || event.altKey) {
    return true;
  }

  if (allowedControlKeys.has(event.key)) {
    return true;
  }

  return /^\d$/.test(event.key);
}
