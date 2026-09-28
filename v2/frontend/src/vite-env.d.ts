/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 백엔드 없이 프론트만 띄울 때 목 API 를 끼운다 (`VITE_USE_MOCK=1 npm run dev`). */
  readonly VITE_USE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
