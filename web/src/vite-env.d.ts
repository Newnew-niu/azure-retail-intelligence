/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the seller API. Defaults to "/api"; empty means no API in this build. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
