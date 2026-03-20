import axios from "axios";

type AuthHooks = {
  getCsrfToken: () => string | null;
  onUnauthorized: () => void;
};

const localhostHostnames = new Set(["localhost", "127.0.0.1", "[::1]"]);

function isLocalHttpUrl(value: URL) {
  return value.protocol === "http:" && localhostHostnames.has(value.hostname);
}

function resolveApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!configured) {
    return "/api";
  }

  if (configured.startsWith("/")) {
    return configured.replace(/\/$/, "") || "/api";
  }

  const parsed = new URL(configured);
  if (parsed.protocol === "https:" || isLocalHttpUrl(parsed)) {
    return parsed.toString().replace(/\/$/, "");
  }

  throw new Error(`Unsafe VITE_API_BASE_URL "${configured}". Use HTTPS or a localhost HTTP origin.`);
}

let authHooks: AuthHooks = {
  getCsrfToken: () => null,
  onUnauthorized: () => undefined,
};

export const apiClient = axios.create({
  baseURL: resolveApiBaseUrl(),
  timeout: 180000,
  withCredentials: true,
});

apiClient.interceptors.request.use((config) => {
  const method = (config.method ?? "get").toLowerCase();
  if (!["get", "head", "options"].includes(method)) {
    const csrfToken = authHooks.getCsrfToken();
    if (csrfToken) {
      config.headers.set("X-CSRF-Token", csrfToken);
    }
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = axios.isAxiosError(error) ? error.config?.url ?? "" : "";
    const isLoginRequest = requestUrl.includes("/auth/login");
    if (axios.isAxiosError(error) && error.response?.status === 401 && !isLoginRequest) {
      authHooks.onUnauthorized();
    }
    return Promise.reject(error);
  },
);

export function buildApiUrl(path: string) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const base = resolveApiBaseUrl();
  if (base.startsWith("/")) {
    return `${base}${normalizedPath}`;
  }
  return `${base}${normalizedPath}`;
}

export function registerAuthStateHooks(nextHooks: AuthHooks) {
  authHooks = nextHooks;
}
