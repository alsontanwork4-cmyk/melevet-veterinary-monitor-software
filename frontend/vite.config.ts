import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function securityHeaders({ allowInlineScripts }: { allowInlineScripts: boolean }) {
  const scriptSrc = allowInlineScripts
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self'";

  return {
    "Content-Security-Policy":
      `default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; img-src 'self' data: blob:; ${scriptSrc}; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self' https: http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*`,
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_DEV_API_ORIGIN?.trim() || "http://localhost:8000";
  const appVersion = env.VITE_APP_VERSION?.trim() || "0.0.0";

  return {
    define: {
      __APP_VERSION__: JSON.stringify(appVersion),
    },
    plugins: [react()],
    server: {
      port: 5173,
      headers: securityHeaders({ allowInlineScripts: true }),
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: false,
          secure: false,
        },
      },
    },
    preview: {
      headers: securityHeaders({ allowInlineScripts: false }),
    },
  };
});
