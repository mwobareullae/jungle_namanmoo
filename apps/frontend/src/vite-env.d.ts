/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_MODE?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_ENABLE_MOCKS?: string;
  readonly VITE_GA_MEASUREMENT_ID?: string;
  readonly VITE_IMAGE_CDN_BASE_URL?: string;
  readonly VITE_GOOGLE_CLIENT_ID?: string;
  readonly VITE_USE_AUTH_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
