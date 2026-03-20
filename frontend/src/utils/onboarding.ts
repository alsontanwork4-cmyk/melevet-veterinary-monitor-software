export const ONBOARDING_STORAGE_KEY = "melevet.onboarding.completed.v1";
const ONBOARDING_OPEN_EVENT = "melevet:onboarding:open";

export function hasCompletedOnboarding(): boolean {
  return window.localStorage.getItem(ONBOARDING_STORAGE_KEY) === "true";
}

export function markOnboardingCompleted(): void {
  window.localStorage.setItem(ONBOARDING_STORAGE_KEY, "true");
}

export function replayOnboarding(): void {
  window.dispatchEvent(new CustomEvent(ONBOARDING_OPEN_EVENT));
}

export function subscribeOnboardingReplay(listener: () => void): () => void {
  window.addEventListener(ONBOARDING_OPEN_EVENT, listener);
  return () => window.removeEventListener(ONBOARDING_OPEN_EVENT, listener);
}
