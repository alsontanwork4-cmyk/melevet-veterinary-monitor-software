/// <reference types="vite/client" />

declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  readonly VITE_LOCAL_APP_MODE?: string;
  readonly VITE_LOCAL_APP_USER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
