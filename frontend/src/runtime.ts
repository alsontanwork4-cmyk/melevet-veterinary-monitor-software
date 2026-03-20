export const isLocalAppMode = import.meta.env.VITE_LOCAL_APP_MODE === "true";

export const localAppUserName = import.meta.env.VITE_LOCAL_APP_USER?.trim() || "Local workstation";
